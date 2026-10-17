"""Reviewable demo drafts; measured observations never imply merge approval."""

import json

from ci_agent.experiments.shadow_mode import evaluate_shadow_pair
from ci_agent.reporting.live_report import write_live_report


def publish_shadow_draft(client, report, output):
    if report.get("draft_pr_url"):
        return report
    if report.get("publication_intent"):
        raise ValueError("Publication already attempted; reconcile GitHub before retrying")
    if report.get("evaluation_mode") != "shadow" or report.get("status") != "completed":
        raise ValueError("A completed Shadow Runner demo report is required")
    fork = report["fork"]
    if client.authenticated_user()["login"].casefold() != fork["owner"].casefold():
        raise ValueError("Draft must stay in the authenticated user's fork")
    runs = report["runs"]
    if len(runs) != 2 or {r["variant"] for r in runs} != {"baseline", "candidate"}:
        raise ValueError("One baseline and candidate receipt are required")
    raw = {r["variant"]: r["evidence"] for r in runs}
    for variant, run in raw.items():
        if run.get("head_sha") != fork[f"{variant}_sha"]:
            raise ValueError("Run revision differs from the proposed branch")
    from ci_agent.experiments.live_loop import count_workflow_jobs, workflow

    baseline = (output / "baseline.yml").read_text(encoding="utf-8")
    candidate = (output / "candidate.yml").read_text(encoding="utf-8")
    if report["inputs"].get("optimization") == "service_readiness":
        from ci_agent.experiments.live_proposal import validate_service_polling

        validate_service_polling(baseline, candidate)
    else:
        from ci_agent.experiments.live_loop import validate_parallelism

        validate_parallelism(baseline, candidate, list(workflow(baseline)["jobs"]))
    expected = count_workflow_jobs(baseline, list(workflow(baseline)["jobs"]))
    measured = evaluate_shadow_pair(raw["baseline"], raw["candidate"], expected)
    if any(report.get(k) != v for k, v in measured.items()):
        raise ValueError("Demo summary differs from raw run evidence")
    # Verify the actual branch diff before making it reviewable.
    for variant in ("baseline", "candidate"):
        comparison = client._get(
            f"/repos/{fork['owner']}/{fork['name']}/compare/{fork['base_sha']}...{fork[variant + '_sha']}"
        )
        if comparison.get("status") != "ahead" or [
            f["filename"] for f in comparison.get("files", [])
        ] != [fork["workflow_path"]]:
            raise ValueError("Draft contains changes beyond the reviewed workflow")
        current = client._get(
            f"/repos/{fork['owner']}/{fork['name']}/git/ref/heads/{fork[variant + '_branch']}"
        )
        if current["object"]["sha"] != fork[variant + "_sha"]:
            raise ValueError("Experiment branch moved after measurement")
    description = (
        "Reduce PostgreSQL health polling interval from 10s to 1s and increase retries from 5 to 50. "
        "All test commands and the full matrix are preserved. The nominal polling budget is preserved; "
        "slow failed probes can extend the worst-case failure window."
        if report["inputs"].get("optimization") == "service_readiness"
        else "Allow independent CI jobs to run concurrently while preserving every required job and command."
    )
    body = [
        "Demo comparison for human review.",
        "",
        description,
        "",
        f"Shadow Runner policy: one pair, workflow elapsed time, 5% threshold. Outcome: **{measured['outcome']}**.",
        (
            f"Baseline: {measured['baseline_duration_s']:.1f}s. Candidate: {measured['proposed_duration_s']:.1f}s. "
            f"Observed elapsed-time change: {measured['saving_pct']:.2f}% reduction."
        ),
        f"Baseline checks passed: {measured['baseline_passed']}. Candidate checks passed: {measured['proposed_passed']}.",
        "",
        (
            "Single-pair observation, not a verified optimization or a statistical guarantee. "
            "Cache/host conditions were not controlled. No automatic merge."
        ),
        "",
        "## Run evidence",
        "",
    ]
    for receipt in runs + report.get("additional_observations", []):
        run = receipt["evidence"]
        body.append(
            f"- Pair {receipt['pair']} {receipt['variant']}: {run['html_url']} — {run.get('conclusion')}"
        )
    if report.get("failed_checks"):
        body += [
            "",
            "## Known failures from later repeated runs",
            "",
            "Later repeats failed required checks. This draft does not resolve or waive those failures.",
        ]
        body += [
            f"- {job['name']}: {', '.join(job.get('failed_steps', []))}"
            for job in report["failed_checks"]
        ]
    repairs = report.get("inputs", {}).get("common_source_files", {})
    body += [
        "",
        "Both branches share baseline repairs: " + ", ".join(sorted(repairs)) + ". "
        "Those repairs are outside this optimization diff. The PR base is the experiment baseline branch.",
    ]

    def save():
        temporary = output / "report.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")
        write_live_report(output, report)

    report["publication_intent"] = {"status": "pending", "mode": "shadow_demo"}
    save()
    try:
        pr = client.create_draft_pull_request(
            fork["owner"],
            fork["name"],
            head=fork["candidate_branch"],
            base=fork["baseline_branch"],
            title="[DEMO] CI workflow optimization — single-pair review",
            body="\n".join(body),
        )
        if not pr.get("html_url"):
            raise ValueError("GitHub omitted the draft URL")
    except Exception:
        report["publication_intent"]["status"] = "unknown"
        save()
        raise
    report.update(
        draft_pr_url=pr["html_url"], publication=f"Demo draft for human review: {pr['html_url']}"
    )
    report["publication_intent"]["status"] = "created"
    save()
    return report
