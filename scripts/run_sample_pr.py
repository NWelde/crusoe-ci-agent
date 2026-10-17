"""Run a labeled baseline/candidate sample on the existing team fork and open a draft PR."""

from __future__ import annotations

import base64
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ci_agent.github.runs import GitHubAPIError, GitHubClient

OWNER = "NWelde"
REPO = "jsonb_accessor"
UPSTREAM = "madeintandem/jsonb_accessor"
WORKFLOW_PATH = ".github/workflows/ci.yml"
EXPECTED_PARENT = UPSTREAM
REQUIRED_CHECKS = ("lint", "tests")
TEST_JOB_PREFIX = "Active Record "
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/bro-15-integration"


def log(message: str) -> None:
    print(message, flush=True)


def contents_text(payload: dict) -> str:
    try:
        return base64.b64decode(payload["content"], validate=False).decode("utf-8")
    except (KeyError, ValueError, UnicodeDecodeError):
        raise GitHubAPIError("GitHub workflow content could not be decoded") from None


def summarize_run(client: GitHubClient, run: dict, expected_sha: str) -> dict:
    run_id = int(run["id"])
    raw_jobs = client.run_jobs(OWNER, REPO, run_id)
    summaries = []
    for job in raw_jobs:
        started = job.get("started_at")
        completed = job.get("completed_at")
        duration = None
        if started and completed:
            try:
                delta = datetime.fromisoformat(completed) - datetime.fromisoformat(started)
                if delta.total_seconds() >= 0:
                    duration = round(delta.total_seconds(), 3)
            except ValueError:
                duration = None
        name = str(job.get("name") or "")
        check = "lint" if name == "lint" else "tests" if name.startswith(TEST_JOB_PREFIX) else None
        summaries.append({
            "id": str(job.get("id")), "name": name, "status": job.get("status"),
            "conclusion": job.get("conclusion"), "check": check,
            "started_at": started, "completed_at": completed, "duration_seconds": duration,
        })
    grouped = {
        name: [job for job in summaries if job["check"] == name]
        for name in REQUIRED_CHECKS
    }
    check_results = {
        name: bool(jobs) and all(job["conclusion"] == "success" for job in jobs)
        for name, jobs in grouped.items()
    }
    runner_seconds = sum(
        job["duration_seconds"] or 0 for jobs in grouped.values() for job in jobs
    )
    expected_matrix_jobs = len(raw_jobs) - len(grouped["lint"])
    return {
        "run_id": str(run_id), "workflow_id": str(run.get("workflow_id")),
        "branch": run.get("head_branch"), "source_revision": run.get("head_sha"),
        "expected_source_revision": expected_sha,
        "revision_matches": run.get("head_sha") == expected_sha,
        "status": run.get("status"), "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"), "updated_at": run.get("updated_at"),
        "required_check_results": check_results,
        "required_job_counts": {name: len(jobs) for name, jobs in grouped.items()},
        "matrix_job_count_observed": expected_matrix_jobs,
        "required_runner_seconds": round(runner_seconds, 3),
        "required_runner_minutes": round(runner_seconds / 60, 3),
        "jobs": summaries,
        "evidence_class": "LIVE_GITHUB_ACTIONS_RUNS",
    }


def wait_for_dispatch(client: GitHubClient, workflow_id: str, branch: str, sha: str, since: datetime) -> dict:
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        for run in client.find_dispatch_run(OWNER, REPO, workflow_id, branch):
            try:
                created = datetime.fromisoformat(run["created_at"])
            except (KeyError, ValueError):
                continue
            if created >= since and run.get("head_sha") == sha:
                return run
        time.sleep(5)
    raise TimeoutError(f"No dispatched run appeared for {branch}")


def wait_for_completion(client: GitHubClient, run: dict, label: str) -> dict:
    run_id = int(run["id"])
    deadline = time.monotonic() + 60 * 60
    while time.monotonic() < deadline:
        current = client.get_run(OWNER, REPO, run_id)
        if current.get("status") == "completed":
            return current
        log(f"{label} run {run_id} is {current.get('status')}; checking again in 30s")
        time.sleep(30)
    raise TimeoutError(f"Run {run_id} did not complete within 60 minutes")


def main() -> int:
    client = GitHubClient.from_git_credential()
    identity = client._get("/user")
    if identity.get("login", "").casefold() != OWNER.casefold():
        raise GitHubAPIError("Git credential account does not match the existing team-fork owner")
    repository = client.repository(OWNER, REPO)
    parent = (repository.get("parent") or {}).get("full_name")
    if not repository.get("fork") or parent != EXPECTED_PARENT:
        raise GitHubAPIError("Configured sample target is not the expected fork of the selected upstream")
    if not repository.get("permissions", {}).get("push"):
        raise GitHubAPIError("Authenticated GitHub account cannot push to the team fork")
    base = repository.get("default_branch")
    ref = client._get(f"/repos/{OWNER}/{REPO}/git/ref/heads/{base}")
    base_sha = ref["object"]["sha"]
    workflows = client._get(f"/repos/{OWNER}/{REPO}/actions/workflows").get("workflows", [])
    workflow = next((item for item in workflows if item.get("path") == WORKFLOW_PATH), None)
    if not workflow or workflow.get("state") != "active":
        raise GitHubAPIError("Active .github/workflows/ci.yml was not found on the team fork")
    workflow_id = str(workflow["id"])
    source_file = client.get_contents(OWNER, REPO, WORKFLOW_PATH, base)
    original = contents_text(source_file)
    if "workflow_dispatch:" not in original:
        raise GitHubAPIError("Fork workflow lacks workflow_dispatch; refusing to edit the default branch to add it")
    change = re.sub(r"(?m)^    needs:\s*lint\s*\r?\n", "", original)
    if change == original or original.count("    needs: lint") != 1:
        raise GitHubAPIError("Expected exactly one tests -> lint dependency in the workflow")
    if "bundle exec rubocop" not in change or "bundle exec rake spec" not in change:
        raise GitHubAPIError("Candidate workflow would not preserve lint and test commands")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    baseline_branch = f"codex/bro15-sample-baseline-{stamp}"
    candidate_branch = f"codex/bro15-sample-independent-tests-{stamp}"
    log(f"Verified writable fork {OWNER}/{REPO} at {base_sha}; workflow {workflow_id}.")
    log("Creating a baseline probe branch from the current default-branch commit.")
    client.create_branch(OWNER, REPO, baseline_branch, base_sha)
    client.put_file(
        OWNER, REPO, ".github/sample-probes/bro15-baseline.md",
        f"Sample baseline probe only. Base revision: {base_sha}.\n",
        "chore(sample): prepare baseline workflow measurement", baseline_branch,
    )
    baseline_sha_ref = client._get(f"/repos/{OWNER}/{REPO}/git/ref/heads/{baseline_branch}")
    baseline_sha = baseline_sha_ref["object"]["sha"]
    baseline_since = datetime.now(UTC)
    client.dispatch_workflow(OWNER, REPO, workflow_id, baseline_branch)
    baseline_queued = wait_for_dispatch(client, workflow_id, baseline_branch, baseline_sha, baseline_since)
    log(f"Baseline workflow run appeared: {baseline_queued['id']}.")

    log("Creating the candidate branch from the exact same base revision.")
    client.create_branch(OWNER, REPO, candidate_branch, base_sha)
    client.put_file(
        OWNER, REPO, WORKFLOW_PATH, change,
        "feat(sample): let CI tests run independently of lint", candidate_branch,
        existing_sha=source_file["sha"],
    )
    candidate_sha_ref = client._get(f"/repos/{OWNER}/{REPO}/git/ref/heads/{candidate_branch}")
    candidate_sha = candidate_sha_ref["object"]["sha"]
    candidate_since = datetime.now(UTC)
    client.dispatch_workflow(OWNER, REPO, workflow_id, candidate_branch)
    candidate_queued = wait_for_dispatch(client, workflow_id, candidate_branch, candidate_sha, candidate_since)
    log(f"Candidate workflow run appeared: {candidate_queued['id']}.")

    log("Waiting for both real GitHub Actions runs to complete.")
    baseline_final = wait_for_completion(client, baseline_queued, "Baseline")
    candidate_final = wait_for_completion(client, candidate_queued, "Candidate")
    baseline = summarize_run(client, baseline_final, baseline_sha)
    candidate = summarize_run(client, candidate_final, candidate_sha)
    runner_delta = round(candidate["required_runner_seconds"] - baseline["required_runner_seconds"], 3)
    baseline_cells = sum(
        job["check"] == "tests" and job["name"].startswith(TEST_JOB_PREFIX)
        and "${{" not in job["name"] for job in baseline["jobs"]
    )
    candidate_cells = sum(
        job["check"] == "tests" and job["name"].startswith(TEST_JOB_PREFIX)
        and "${{" not in job["name"] for job in candidate["jobs"]
    )

    pr_body = f"""# SAMPLE PR — independent CI test feedback

> Review/demo only. This is not a verified runner-minute optimization and must not be merged as a BRO-15 win.

## Change

Remove the `tests` job's `needs: lint` dependency so the full test matrix runs even when RuboCop fails. Both the `lint` check and every test matrix cell remain enabled.

## Fresh matched-commit Actions sample

- Repository: `{OWNER}/{REPO}` (team-controlled fork of `{UPSTREAM}`).
- Common base: `{base_sha}`; baseline and candidate branches both start from this revision.
- Baseline run: [{baseline['run_id']}](https://github.com/{OWNER}/{REPO}/actions/runs/{baseline['run_id']}) — `{baseline['conclusion']}`, checks `{json.dumps(baseline['required_check_results'])}`, {baseline_cells} matrix cells expanded, {baseline['required_runner_minutes']} required runner-minutes.
- Candidate run: [{candidate['run_id']}](https://github.com/{OWNER}/{REPO}/actions/runs/{candidate['run_id']}) — `{candidate['conclusion']}`, checks `{json.dumps(candidate['required_check_results'])}`, {candidate_cells} matrix cells, {candidate['required_runner_minutes']} required runner-minutes.
- Candidate minus baseline required runner time: {runner_delta} seconds.

## Interpretation

This change targets feedback latency and failure isolation, not reduced runner minutes. If lint fails, running the matrix may consume substantially more runner time; it does not bypass the required lint check. The project success contract requires a runner-minute reduction, so this sample is not evidence for an optimization win. Keep as a review example only; do not merge unless the project explicitly accepts this tradeoff.

## Validation

Only this workflow dependency changed. Both runs were dispatched on the same fork, workflow, and common base. The baseline probe branch has a marker file only to make that sample branch observable; it is not in this PR. Compare the Actions pages for per-job conclusions and timings. No merge was performed.
"""
    title = "[SAMPLE] Run CI test matrix independently of lint"
    pr = client.create_draft_pull_request(
        OWNER, REPO, head=candidate_branch, base=base, title=title, body=pr_body,
    )
    report = {
        "evidence_class": "LIVE_GITHUB_ACTIONS_RUNS",
        "repository": f"{OWNER}/{REPO}", "upstream": UPSTREAM,
        "base_branch": base, "common_base_revision": base_sha,
        "workflow_id": workflow_id, "workflow_path": WORKFLOW_PATH,
        "candidate_change": "Remove `needs: lint` from tests job; keep all required checks enabled.",
        "baseline_branch": baseline_branch, "baseline_branch_commit": baseline_sha,
        "candidate_branch": candidate_branch, "candidate_branch_commit": candidate_sha,
        "baseline": baseline, "candidate": candidate,
        "candidate_minus_baseline_required_runner_seconds": runner_delta,
        "baseline_matrix_cells_expanded": baseline_cells,
        "candidate_matrix_cells": candidate_cells,
        "interpretation": "Feedback-latency sample only; not a required-runner-minute win.",
        "pull_request": {"number": pr.get("number"), "url": pr.get("html_url"), "draft": pr.get("draft")},
        "no_merge_performed": True,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "sample-pr-live-evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "sample-pr-description.md").write_text(pr_body, encoding="utf-8")
    log(f"Draft sample PR created: {pr.get('html_url')}")
    log(f"Live evidence: {OUTPUT / 'sample-pr-live-evidence.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GitHubAPIError, TimeoutError, KeyError, ValueError) as exc:
        print(f"Sample PR workflow stopped safely: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
