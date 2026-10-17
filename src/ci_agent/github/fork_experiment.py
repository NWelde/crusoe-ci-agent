"""Prepare an isolated fork and launch matched GitHub Actions runs.

This is the GitHub execution substrate only. Experiment policy, retries, verdicts,
resume state, and publication gates belong to the continuous runner coordinator.
Forks are retained by default so evidence is recoverable after interruption.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ci_agent.github.runs import GitHubAPIError, GitHubClient


@dataclass(frozen=True)
class PreparedFork:
    upstream: str
    repository: str
    owner: str
    name: str
    default_branch: str
    base_sha: str
    workflow_id: str
    workflow_path: str
    baseline_branch: str
    candidate_branch: str
    baseline_sha: str
    candidate_sha: str


def _repository_parts(value: str) -> tuple[str, str]:
    parts = value.strip().split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts):
        raise ValueError("Repository must be OWNER/REPO")
    return parts[0], parts[1]


def _content_text(payload: dict[str, Any]) -> str:
    try:
        if payload.get("encoding") != "base64":
            raise ValueError
        return base64.b64decode(payload["content"], validate=False).decode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        raise GitHubAPIError("GitHub workflow content could not be decoded") from None


def _branch_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", value).strip("-").lower()
    return (slug or "experiment")[:30]


def prepare_fork_experiment(
    client: GitHubClient,
    upstream: str,
    workflow_path: str,
    candidate_workflow: str,
    *,
    run_key: str,
    baseline_workflow: str | None = None,
    timeout_seconds: int = 120,
    source_sha: str | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    existing_fork: str | None = None,
    common_source_files: dict[str, str] | None = None,
) -> PreparedFork:
    """Create a uniquely named fork with baseline and candidate dispatch refs.

    The caller must validate the candidate before calling this function. Both
    variants begin at the same upstream commit. Only the disposable fork gets
    workflow_dispatch added, when absent, so the upstream is never mutated.
    """
    upstream_owner, upstream_repo = _repository_parts(upstream)
    if not workflow_path.startswith(".github/workflows/") or ".." in workflow_path.split("/"):
        raise ValueError("workflow_path must point inside .github/workflows")
    if not run_key.strip():
        raise ValueError("run_key is required")
    for path, content in (common_source_files or {}).items():
        if (not path or path.startswith(("/", "\\", ".github/workflows/")) or "\\" in path
                or ":" in path or any(p in {".", "..", ".git"} for p in path.split("/"))
                or not isinstance(content, str)):
            raise ValueError("Common source files must be repository-relative non-workflow text files")
    identity = client.authenticated_user()
    fork_owner = str(identity.get("login") or "")
    if not fork_owner:
        raise GitHubAPIError("Authenticated GitHub account has no login")
    upstream_repo_data = client.repository(upstream_owner, upstream_repo)
    source_ref = source_sha or str(upstream_repo_data.get("default_branch") or "")
    source = client.get_contents(upstream_owner, upstream_repo, workflow_path, source_ref)
    original = _content_text(source)
    baseline = _add_dispatch(baseline_workflow if baseline_workflow is not None else original)
    candidate = _add_dispatch(candidate_workflow)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    fork_name = f"{upstream_repo[:55]}-exp-{stamp}-{_branch_slug(run_key)[:12]}"
    if existing_fork:
        requested_owner, fork_name = _repository_parts(existing_fork)
        if requested_owner.casefold() != fork_owner.casefold():
            raise GitHubAPIError("Existing fork must belong to the authenticated account")
        fork = client.repository(fork_owner, fork_name)
    else:
        if on_progress:
            on_progress({"stage": "fork_requested", "repository": f"{fork_owner}/{fork_name}"})
        created = client.fork_repository(upstream_owner, upstream_repo, name=fork_name)
        if created.get("full_name", "").casefold() != f"{fork_owner}/{fork_name}".casefold():
            raise GitHubAPIError(
                "GitHub did not create the requested isolated fork; an existing fork may already "
                "occupy this account's fork network. Select --fork-repository explicitly."
            )
        fork = client.wait_for_repository(fork_owner, fork_name, timeout_seconds=timeout_seconds)
    if fork.get("full_name", "").casefold() != f"{fork_owner}/{fork_name}".casefold():
        raise GitHubAPIError("GitHub returned a fork with an unexpected owner or name")
    parent = fork.get("parent") or {}
    if str(parent.get("full_name", "")).casefold() != upstream.casefold():
        raise GitHubAPIError("Created repository is not a fork of the requested upstream")
    if not existing_fork:
        client.set_actions_enabled(fork_owner, fork_name, True)
    default_branch, _initial_sha = client.default_branch(fork_owner, fork_name)
    if source_sha:
        _initial_sha = source_sha
    baseline_branch = f"codex/{_branch_slug(run_key)}-baseline-{stamp[-6:]}"
    candidate_branch = f"codex/{_branch_slug(run_key)}-candidate-{stamp[-6:]}"
    if on_progress:
        on_progress({"stage": "branches_preparing", "repository": f"{fork_owner}/{fork_name}",
                     "baseline_branch": baseline_branch, "candidate_branch": candidate_branch,
                     "source_sha": _initial_sha})
    # Fork the exact upstream commit so drift between source inspection and
    # GitHub's asynchronous fork creation cannot silently change the baseline.
    # Baseline repairs are explicit and identical in both variants, so a broken
    # upstream check cannot be repaired only for the proposed optimization.
    if common_source_files:
        branch = f"codex/{_branch_slug(run_key)}-source-{stamp[-6:]}"
        client.create_branch(fork_owner, fork_name, branch, _initial_sha)
        for path, content in sorted((common_source_files or {}).items()):
            existing = client.get_contents(fork_owner, fork_name, path, branch)
            prepared = client.put_file(
                fork_owner, fork_name, path, content,
                f"ci-agent: common baseline preparation {run_key}", branch,
                existing_sha=existing.get("sha"),
            )
            _initial_sha = str(prepared["commit"]["sha"])
        if on_progress:
            on_progress({"stage": "source_prepared", "source_sha": _initial_sha,
                         "files": sorted(common_source_files)})
    client.create_branch(fork_owner, fork_name, baseline_branch, _initial_sha)
    client.create_branch(fork_owner, fork_name, candidate_branch, _initial_sha)
    baseline_file = client.get_contents(fork_owner, fork_name, workflow_path, baseline_branch)
    baseline_commit = client.put_file(
        fork_owner, fork_name, workflow_path, baseline,
        f"ci-agent: prepare baseline {run_key}", baseline_branch,
        existing_sha=baseline_file.get("sha"),
    )
    baseline_sha = str(baseline_commit["commit"]["sha"])
    candidate_file = client.get_contents(fork_owner, fork_name, workflow_path, candidate_branch)
    candidate_commit = client.put_file(
        fork_owner, fork_name, workflow_path, candidate,
        f"ci-agent: prepare candidate {run_key}", candidate_branch,
        existing_sha=candidate_file.get("sha"),
    )
    candidate_sha = str(candidate_commit["commit"]["sha"])
    workflow = client.workflow(fork_owner, fork_name, workflow_path)
    return PreparedFork(
        upstream=upstream, repository=f"{fork_owner}/{fork_name}", owner=fork_owner,
        name=fork_name, default_branch=default_branch, base_sha=_initial_sha,
        workflow_id=str(workflow["id"]), workflow_path=workflow_path,
        baseline_branch=baseline_branch, candidate_branch=candidate_branch,
        baseline_sha=baseline_sha, candidate_sha=candidate_sha,
    )


def dispatch_matched_runs(
    client: GitHubClient,
    fork: PreparedFork,
    *,
    dispatch_timeout_seconds: int = 240,
    run_timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Dispatch and collect exact baseline/candidate runs and all job pages."""
    owner, repo = fork.owner, fork.name
    runs: dict[str, Any] = {}
    for variant, branch, sha in (
        ("baseline", fork.baseline_branch, fork.baseline_sha),
        ("candidate", fork.candidate_branch, fork.candidate_sha),
    ):
        dispatched_after = datetime.now(UTC)
        client.dispatch_workflow(owner, repo, fork.workflow_id, branch)
        appeared = client.wait_for_dispatch_run(
            owner, repo, fork.workflow_id, branch, sha,
            dispatched_after=dispatched_after, timeout_seconds=dispatch_timeout_seconds,
        )
        run_id = int(appeared["id"])
        client.wait_for_run_completion(
            owner, repo, run_id, timeout_seconds=run_timeout_seconds,
        )
        details = client.full_run(owner, repo, run_id)
        if str(details.get("head_sha") or "") != sha:
            raise GitHubAPIError(f"{variant} run completed on an unexpected source revision")
        runs[variant] = {
            "run": details,
            "url": details.get("html_url"),
            "jobs_count": len(details["jobs"]),
        }
    return {"evidence_class": "LIVE_GITHUB_ACTIONS_RUNS", "fork": fork.__dict__, "runs": runs}


def _add_dispatch(raw_yaml: str) -> str:
    """Ensure workflow_dispatch exists in YAML for the temporary fork workflow."""
    import yaml

    config = yaml.safe_load(raw_yaml) or {}
    # PyYAML uses YAML 1.1 where bare `on` can parse as boolean True.
    trigger = config.pop("on", config.pop(True, None))
    if trigger is None:
        triggers: dict[str, Any] = {}
    elif isinstance(trigger, str):
        triggers = {trigger: None}
    elif isinstance(trigger, list):
        triggers = {event: None for event in trigger}
    elif isinstance(trigger, dict):
        triggers = dict(trigger)
    else:
        raise ValueError("Workflow has unsupported trigger syntax")
    triggers.setdefault("workflow_dispatch", None)
    config["on"] = triggers
    return yaml.safe_dump(config, sort_keys=False)
