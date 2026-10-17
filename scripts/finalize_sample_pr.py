"""Finalize a sample draft PR from already-completed matched GitHub Actions runs."""

from __future__ import annotations

import json
import sys

from run_sample_pr import OWNER, REPO, ROOT, UPSTREAM, WORKFLOW_PATH, summarize_run

from ci_agent.github.runs import GitHubAPIError, GitHubClient


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python scripts/finalize_sample_pr.py BASELINE_RUN_ID CANDIDATE_RUN_ID")
    baseline_id, candidate_id = map(int, sys.argv[1:])
    client = GitHubClient.from_git_credential()
    identity = client._get("/user")
    if identity.get("login", "").casefold() != OWNER.casefold():
        raise GitHubAPIError("Git credential account does not match the team-fork owner")
    repository = client.repository(OWNER, REPO)
    base = repository["default_branch"]
    branch_sha = client._get(f"/repos/{OWNER}/{REPO}/git/ref/heads/{base}")["object"]["sha"]
    workflow_id = "286446768"

    baseline_raw = client.get_run(OWNER, REPO, baseline_id)
    candidate_raw = client.get_run(OWNER, REPO, candidate_id)
    if baseline_raw.get("status") != "completed" or candidate_raw.get("status") != "completed":
        raise GitHubAPIError("Both sample Actions runs must be complete before finalizing the draft")
    baseline_branch = baseline_raw.get("head_branch", "")
    candidate_branch = candidate_raw.get("head_branch", "")
    if not baseline_branch.startswith("codex/bro15-sample-baseline-"):
        raise GitHubAPIError("Baseline run is not from the expected sample branch")
    if not candidate_branch.startswith("codex/bro15-sample-independent-tests-"):
        raise GitHubAPIError("Candidate run is not from the expected sample branch")

    baseline = summarize_run(client, baseline_raw, baseline_raw["head_sha"])
    candidate = summarize_run(client, candidate_raw, candidate_raw["head_sha"])
    runner_delta = round(candidate["required_runner_seconds"] - baseline["required_runner_seconds"], 3)
    baseline_matrix_cells = sum(
        job["check"] == "tests" and job["name"].startswith("Active Record ")
        and "${{" not in job["name"]
        for job in baseline["jobs"]
    )
    candidate_matrix_cells = sum(
        job["check"] == "tests" and job["name"].startswith("Active Record ")
        and "${{" not in job["name"]
        for job in candidate["jobs"]
    )
    passed_cells = sum(
        job["conclusion"] == "success" for job in candidate["jobs"] if job["check"] == "tests"
    )
    failed_cells = sum(
        job["conclusion"] == "failure" for job in candidate["jobs"] if job["check"] == "tests"
    )
    pr_body = f"""# SAMPLE PR — independent CI test feedback

> Review/demo only. This is not a verified runner-minute optimization and must not be merged as a BRO-15 win.

## Change

Remove the `tests` job's `needs: lint` dependency so the full test matrix runs even when RuboCop fails. Both the required `lint` check and all test matrix cells remain enabled.

## Fresh matched-base Actions sample

- Repository: `{OWNER}/{REPO}` (team-controlled fork of `{UPSTREAM}`).
- Common base: `{branch_sha}`. Both run branches were created from this same default-branch commit.
- Baseline run: [{baseline['run_id']}](https://github.com/{OWNER}/{REPO}/actions/runs/{baseline['run_id']}) — `{baseline['conclusion']}`, required checks `{json.dumps(baseline['required_check_results'])}`, {baseline_matrix_cells} matrix cells expanded ({baseline['required_job_counts']['tests']} aggregate tests job was skipped), {baseline['required_runner_minutes']} required runner-minutes.
- Candidate run: [{candidate['run_id']}](https://github.com/{OWNER}/{REPO}/actions/runs/{candidate['run_id']}) — `{candidate['conclusion']}`, required checks `{json.dumps(candidate['required_check_results'])}`, {candidate_matrix_cells} matrix cells, {candidate['required_runner_minutes']} required runner-minutes.
- Candidate test matrix: {passed_cells} passed, {failed_cells} failed.
- Candidate minus baseline required runner time: {runner_delta} seconds.

## Interpretation

This change targets feedback latency and failure isolation, not reduced runner minutes. In this sample, lint failed in both runs. The baseline skipped the dependent test matrix; the candidate ran it but the test matrix also had failures. The candidate consumed more required runner time and did not pass the required checks. It is not a product win and must not be merged as a performance optimization. Keep this draft only as a review example of the real-run sampling and PR gate.

## Validation

The workflow dependency is the only candidate change. Both runs used the same team fork, workflow, and common source base. The baseline probe branch has a separate marker file only to make the sample branch observable; that marker is not in this PR. No merge was performed.
"""

    existing = client.open_pull_requests(OWNER, REPO, head=f"{OWNER}:{candidate_branch}", base=base)
    if existing:
        pr = existing[0]
        pr = client._write("PATCH", f"/repos/{OWNER}/{REPO}/pulls/{pr['number']}", body={
            "title": "[SAMPLE] Run CI test matrix independently of lint", "body": pr_body,
        })
    else:
        pr = client.create_draft_pull_request(
            OWNER, REPO, head=candidate_branch, base=base,
            title="[SAMPLE] Run CI test matrix independently of lint", body=pr_body,
        )

    report = {
        "evidence_class": "LIVE_GITHUB_ACTIONS_RUNS", "repository": f"{OWNER}/{REPO}",
        "upstream": UPSTREAM, "base_branch": base, "common_base_revision": branch_sha,
        "workflow_id": workflow_id, "workflow_path": WORKFLOW_PATH,
        "candidate_change": "Remove needs: lint from tests job; required checks remain enabled.",
        "baseline_branch": baseline_branch, "candidate_branch": candidate_branch,
        "baseline": baseline, "candidate": candidate,
        "candidate_minus_baseline_required_runner_seconds": runner_delta,
        "baseline_matrix_cells_expanded": baseline_matrix_cells,
        "candidate_matrix_cells": candidate_matrix_cells,
        "candidate_matrix_passed": passed_cells, "candidate_matrix_failed": failed_cells,
        "interpretation": "Not a runner-minute win; draft PR is a review example only.",
        "pull_request": {"number": pr.get("number"), "url": pr.get("html_url"), "draft": pr.get("draft")},
        "no_merge_performed": True,
    }
    out = ROOT / "artifacts/bro-15-integration"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample-pr-live-evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "sample-pr-description.md").write_text(pr_body, encoding="utf-8")
    print(f"Draft sample PR: {pr.get('html_url')}", flush=True)
    print(f"Live run evidence: {out / 'sample-pr-live-evidence.json'}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GitHubAPIError, KeyError, ValueError) as exc:
        print(f"Could not finalize sample PR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
