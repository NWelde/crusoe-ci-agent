"""Read-only GitHub Actions run sampling, adapted from Shadow Runner ingestion.

This module reads run history and job timings from GitHub's REST API. It never
dispatches workflows or changes repository state.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from ci_agent.models import JobSnapshot, RunSnapshot

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubAPIError(RuntimeError):
    """GitHub API error with response bodies and credentials omitted."""


class GitHubClient:
    def __init__(
        self, token: str, *, session: requests.Session | None = None, timeout: float = 30
    ) -> None:
        if not token.strip():
            raise ValueError("GITHUB_TOKEN is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._token = token.strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    @classmethod
    def from_env(cls, *, dotenv_path: Path | None = None) -> GitHubClient:
        """Load an optional .env and require the token without displaying it."""
        load_dotenv(dotenv_path=dotenv_path, override=False)
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if not token:
            raise GitHubAPIError("GITHUB_TOKEN is missing; configure it in the environment or .env")
        return cls(token)

    @classmethod
    def from_git_credential(cls) -> GitHubClient:
        """Use Git Credential Manager's existing HTTPS credential without printing it."""
        try:
            result = subprocess.run(
                ["git", "credential", "fill"],
                input="protocol=https\nhost=github.com\n\n",
                capture_output=True, text=True, timeout=15, check=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise GitHubAPIError("No usable GitHub credential is available from Git Credential Manager") from None
        fields = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        token = fields.get("password", "").strip()
        if not token:
            raise GitHubAPIError("Git Credential Manager returned no GitHub token")
        return cls(token)

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{API_BASE}{path}",
                params=params,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self._token}",
                    "X-GitHub-Api-Version": API_VERSION,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GitHubAPIError(f"GitHub request failed ({type(exc).__name__})") from None
        if response.status_code != 200:
            hint = "; check repository access or token scopes" if response.status_code in {401, 403, 404} else ""
            raise GitHubAPIError(f"GitHub API returned HTTP {response.status_code}{hint}")
        try:
            result = response.json()
        except ValueError:
            raise GitHubAPIError("GitHub API returned invalid JSON") from None
        if not isinstance(result, dict):
            raise GitHubAPIError("GitHub API returned an unexpected response shape")
        return result

    def _write(
        self, method: str, path: str, *, body: dict[str, Any] | None = None,
        accepted: tuple[int, ...] = (200, 201, 202, 204),
    ) -> dict[str, Any]:
        """Issue one authenticated repository write; never include response bodies in errors."""
        try:
            response = self.session.request(
                method, f"{API_BASE}{path}", json=body,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self._token}",
                    "X-GitHub-Api-Version": API_VERSION,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GitHubAPIError(f"GitHub write failed ({type(exc).__name__})") from None
        if response.status_code not in accepted:
            hint = "; check token contents and pull-request write permissions" if response.status_code in {401, 403, 404} else ""
            raise GitHubAPIError(f"GitHub API write returned HTTP {response.status_code}{hint}")
        if response.status_code == 204 or not response.content:
            return {}
        try:
            result = response.json()
        except ValueError:
            raise GitHubAPIError("GitHub write returned invalid JSON") from None
        if not isinstance(result, dict):
            raise GitHubAPIError("GitHub write returned an unexpected response shape")
        return result

    def authenticated_user(self) -> dict[str, Any]:
        """Return the authenticated account identity without exposing its token."""
        return self._get("/user")

    def fork_repository(self, owner: str, repo: str, *, name: str | None = None) -> dict[str, Any]:
        """Create a fork under the authenticated user; GitHub provisions it asynchronously."""
        body = {"name": name} if name else None
        return self._write("POST", f"/repos/{owner}/{repo}/forks", body=body, accepted=(202,))

    def set_actions_enabled(self, owner: str, repo: str, enabled: bool = True) -> None:
        self._write("PUT", f"/repos/{owner}/{repo}/actions/permissions",
                    body={"enabled": enabled}, accepted=(204,))

    def default_branch(self, owner: str, repo: str) -> tuple[str, str]:
        repository = self.repository(owner, repo)
        branch = str(repository.get("default_branch") or "")
        if not branch:
            raise GitHubAPIError("GitHub repository has no default branch")
        ref = self._get(f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
        try:
            return branch, str(ref["object"]["sha"])
        except (KeyError, TypeError):
            raise GitHubAPIError("GitHub default branch has no commit SHA") from None

    def create_pull_request(
        self, owner: str, repo: str, *, head: str, base: str, title: str, body: str,
        draft: bool = True,
    ) -> dict[str, Any]:
        return self._write("POST", f"/repos/{owner}/{repo}/pulls", body={
            "head": head, "base": base, "title": title, "body": body, "draft": draft,
        }, accepted=(201,))

    def wait_for_repository(self, owner: str, repo: str, *, timeout_seconds: int = 120,
                            poll_seconds: float = 3) -> dict[str, Any]:
        """Wait for GitHub to finish provisioning a newly created fork."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                return self.repository(owner, repo)
            except GitHubAPIError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                time.sleep(poll_seconds)
        raise TimeoutError(f"Fork {owner}/{repo} was not ready before timeout")

    def workflow(self, owner: str, repo: str, path: str) -> dict[str, Any]:
        """Find an active workflow by its full repository path."""
        payload = self._get(f"/repos/{owner}/{repo}/actions/workflows")
        workflows = payload.get("workflows")
        if not isinstance(workflows, list):
            raise GitHubAPIError("GitHub workflow response has no workflows list")
        for workflow in workflows:
            if workflow.get("path") == path and workflow.get("state") == "active":
                return workflow
        raise GitHubAPIError(f"No active workflow found at {path}")

    def wait_for_dispatch_run(
        self, owner: str, repo: str, workflow_id: str, branch: str, expected_sha: str,
        *, dispatched_after: datetime, timeout_seconds: int = 240, poll_seconds: float = 5,
    ) -> dict[str, Any]:
        """Find the dispatch created after this call for the exact branch and SHA."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            for run in self.find_dispatch_run(owner, repo, workflow_id, branch):
                created = _timestamp(run.get("created_at"), "created_at", int(run.get("id") or 0))
                if (created and created >= dispatched_after and
                        str(run.get("head_sha") or "") == expected_sha):
                    return run
            time.sleep(poll_seconds)
        raise TimeoutError(f"No matching dispatched run appeared for branch {branch}")

    def wait_for_run_completion(
        self, owner: str, repo: str, run_id: int, *, timeout_seconds: int = 3600,
        poll_seconds: float = 30,
    ) -> dict[str, Any]:
        """Poll one known Actions run until it completes or the timebox expires."""
        if run_id <= 0:
            raise ValueError("run_id must be positive")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            run = self.get_run(owner, repo, run_id)
            if run.get("status") == "completed":
                return run
            time.sleep(poll_seconds)
        raise TimeoutError(f"GitHub Actions run {run_id} did not complete before timeout")

    def full_run(self, owner: str, repo: str, run_id: int) -> dict[str, Any]:
        """Return run metadata with all paginated jobs attached."""
        result = self.get_run(owner, repo, run_id)
        result["jobs"] = self.run_jobs(owner, repo, run_id)
        return result

    def create_branch(self, owner: str, repo: str, branch: str, source_sha: str) -> None:
        self._write("POST", f"/repos/{owner}/{repo}/git/refs", body={
            "ref": f"refs/heads/{branch}", "sha": source_sha,
        }, accepted=(201,))

    def put_file(
        self, owner: str, repo: str, path: str, content: str, message: str, branch: str,
        *, existing_sha: str | None = None,
    ) -> dict[str, Any]:
        import base64

        body = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if existing_sha:
            body["sha"] = existing_sha
        return self._write("PUT", f"/repos/{owner}/{repo}/contents/{path}", body=body, accepted=(200, 201))

    def create_draft_pull_request(
        self, owner: str, repo: str, *, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        return self._write("POST", f"/repos/{owner}/{repo}/pulls", body={
            "head": head, "base": base, "title": title, "body": body, "draft": True,
        }, accepted=(201,))

    def branch_runs(
        self, owner: str, repo: str, workflow_id: str, branch: str, *, limit: int = 30
    ) -> list[dict[str, Any]]:
        payload = self._get(
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs",
            params={"branch": branch, "event": "push", "per_page": min(limit, 100)},
        )
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise GitHubAPIError("GitHub branch workflow response has no workflow_runs list")
        return runs[:limit]

    def dispatch_workflow(self, owner: str, repo: str, workflow_id: str, ref: str) -> None:
        self._write(
            "POST", f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
            body={"ref": ref}, accepted=(204,),
        )

    def find_dispatch_run(
        self, owner: str, repo: str, workflow_id: str, branch: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        payload = self._get(
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs",
            params={"branch": branch, "event": "workflow_dispatch", "per_page": min(limit, 100)},
        )
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise GitHubAPIError("GitHub dispatch response has no workflow_runs list")
        return runs[:limit]

    def get_run(self, owner: str, repo: str, run_id: int) -> dict[str, Any]:
        return self._get(f"/repos/{owner}/{repo}/actions/runs/{run_id}")

    def get_contents(self, owner: str, repo: str, path: str, ref: str) -> dict[str, Any]:
        return self._get(f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})

    def open_pull_requests(self, owner: str, repo: str, *, head: str, base: str) -> list[dict[str, Any]]:
        try:
            response = self.session.get(
                f"{API_BASE}/repos/{owner}/{repo}/pulls",
                params={"state": "open", "head": head, "base": base, "per_page": 100},
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self._token}",
                    "X-GitHub-Api-Version": API_VERSION,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GitHubAPIError(f"GitHub request failed ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise GitHubAPIError(f"GitHub API returned HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError:
            raise GitHubAPIError("GitHub API returned invalid JSON") from None
        if not isinstance(result, list):
            raise GitHubAPIError("GitHub pull request list has an unexpected response shape")
        return result

    def repository(self, owner: str, repo: str) -> dict[str, Any]:
        return self._get(f"/repos/{owner}/{repo}")

    def recent_runs(self, owner: str, repo: str, *, limit: int = 30) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        payload = self._get(f"/repos/{owner}/{repo}/actions/runs", params={"per_page": limit})
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise GitHubAPIError("GitHub run history response has no workflow_runs list")
        return runs[:limit]

    def run_jobs(self, owner: str, repo: str, run_id: int) -> list[dict[str, Any]]:
        if run_id <= 0:
            raise ValueError("run_id must be positive")
        jobs: list[dict[str, Any]] = []
        for page in range(1, 21):
            payload = self._get(
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
                params={"per_page": 100, "page": page},
            )
            page_jobs = payload.get("jobs")
            if not isinstance(page_jobs, list):
                raise GitHubAPIError(f"GitHub jobs response for run {run_id} has no jobs list")
            jobs.extend(page_jobs)
            total = payload.get("total_count")
            if (isinstance(total, int) and len(jobs) >= total) or len(page_jobs) < 100:
                return jobs
        raise GitHubAPIError(f"GitHub run {run_id} exceeded the safe 2,000-job sampling limit")


def _timestamp(value: str | None, field: str, run_id: int) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise GitHubAPIError(f"Run {run_id} contains invalid {field} timestamp") from None


def sample_runs(
    client: GitHubClient,
    owner: str,
    repo: str,
    *,
    limit: int = 30,
    workflow_id: str | None = None,
    required_checks: tuple[str, ...] = (),
    required_job_patterns: dict[str, tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], tuple[RunSnapshot, ...], dict[str, Any]]:
    """Fetch recent run metadata and jobs, returning validated immutable snapshots."""
    repository = client.repository(owner, repo)
    required_job_patterns = required_job_patterns or {}
    repo_id = str(repository["id"])
    snapshots: list[RunSnapshot] = []
    for raw in client.recent_runs(owner, repo, limit=limit):
        run_id = int(raw["id"])
        if workflow_id is not None and str(raw.get("workflow_id")) != workflow_id:
            continue
        jobs: list[JobSnapshot] = []
        for job in client.run_jobs(owner, repo, run_id):
            started = _timestamp(job.get("started_at"), "job started_at", run_id)
            completed = _timestamp(job.get("completed_at"), "job completed_at", run_id)
            duration = (completed - started).total_seconds() if started and completed else None
            if duration is not None and duration < 0:
                duration = None
            jobs.append(JobSnapshot(
                id=str(job["id"]), name=str(job.get("name") or ""),
                status=str(job.get("status") or "unknown"),
                conclusion=job.get("conclusion"), started_at=started,
                completed_at=completed, duration_seconds=duration,
            ))
        raw_id = str(raw["id"])
        workflow = str(raw.get("workflow_id") or "")
        snapshots.append(RunSnapshot(
            repository_id=repo_id,
            workflow_id=workflow,
            github_run_id=raw_id,
            attempt=int(raw.get("run_attempt") or 1),
            source_revision=str(raw.get("head_sha") or ""),
            status=str(raw.get("status") or "unknown"),
            conclusion=raw.get("conclusion"),
            created_at=_timestamp(raw.get("created_at"), "created_at", run_id),
            started_at=_timestamp(raw.get("run_started_at"), "run_started_at", run_id),
            completed_at=_timestamp(raw.get("updated_at"), "updated_at", run_id),
            jobs=tuple(jobs),
        ))

    report_runs = []
    for run in snapshots:
        jobs_by_name: dict[str, list[JobSnapshot]] = {}
        for job in run.jobs:
            jobs_by_name.setdefault(job.name, []).append(job)
        jobs_for_check = {
            check: [
                job for name, jobs in jobs_by_name.items()
                if name == check or name.startswith(f"{check} (")
                or any(name.startswith(pattern) for pattern in required_job_patterns.get(check, ()))
                for job in jobs
            ]
            for check in required_checks
        }
        jobs_for_check = {
            check: list({job.id: job for job in jobs}.values())
            for check, jobs in jobs_for_check.items()
        }
        check_results = {
            check: bool(jobs) and all(job.conclusion == "success" for job in jobs)
            for check, jobs in jobs_for_check.items()
        }
        seconds = sum(
            job.duration_seconds or 0 for jobs in jobs_for_check.values() for job in jobs
        )
        report_runs.append({
            "run": run.model_dump(mode="json"),
            "required_check_results": check_results,
            "required_job_counts": {check: len(jobs) for check, jobs in jobs_for_check.items()},
            "required_runner_seconds": round(seconds, 3),
            "evidence_class": "LIVE_GITHUB_METADATA",
        })
    result = {
        "repository": f"{owner}/{repo}",
        "repository_id": repo_id,
        "default_branch": repository.get("default_branch"),
        "sampled_at": datetime.now(UTC).isoformat(),
        "workflow_id_filter": workflow_id,
        "required_checks": list(required_checks),
        "required_job_patterns": {key: list(value) for key, value in required_job_patterns.items()},
        "sample_limit": limit,
        "runs_returned": len(report_runs),
        "runs": report_runs,
        "source": "GitHub Actions REST API: workflow runs and per-run jobs",
    }
    fingerprint_payload = result.copy()
    fingerprint_payload.pop("sampled_at")
    result["sample_fingerprint"] = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return repository, tuple(snapshots), result
