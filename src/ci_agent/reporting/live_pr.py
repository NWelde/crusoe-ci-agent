"""Publish only independently verified live wins as reviewable draft PRs."""

import json

from ci_agent.contracts import SealedContract
from ci_agent.experiments.live_evaluation import evaluate_experiment
from ci_agent.reporting.live_report import write_live_report


def publish_verified_draft(client, report, output):
    """Persist intent before creation; ambiguous writes require reconciliation."""
    from pathlib import Path

    output = Path(output)

    def save():
        output.mkdir(parents=True, exist_ok=True)
        temporary = output / "report.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")
        write_live_report(output, report)

    if report.get("draft_pr_url"):
        return report
    if report.get("publication_intent"):
        raise ValueError("Draft publication already attempted; reconcile GitHub before retrying")
    cache = report.get("cache_verification", {})
    if (
        cache.get("matched") is not True
        or len(cache.get("pairs", [])) != 3
        or any(pair.get("matched") is not True for pair in cache.get("pairs", []))
    ):
        raise ValueError("Publication requires matched cache evidence for all three pairs")
    verification = report.get("verification", {})
    if (
        report.get("status") != "completed"
        or report.get("outcome") != "win"
        or verification.get("distinct_runs") != 6
        or verification.get("jobs_per_run", 0) <= 0
        or verification.get("runner_labels_verified") is not True
        or verification.get("method") != "independent raw-evidence recomputation"
    ):
        raise ValueError("Draft publication requires an independently verified complete live win")
    pairs = report.get("pairs", [])
    runs = report.get("runs", [])
    if len(pairs) != 3 or len(runs) != 6:
        raise ValueError("Draft publication requires three pairs and six run receipts")
    sealed = SealedContract.model_validate(report.get("contract"))
    fork = report["fork"]
    source = report.get("source_verification")
    if not source and (output / "source-audit.json").exists():
        source = json.loads((output / "source-audit.json").read_text(encoding="utf-8"))
    if not source or source.get("shared_source_sha") != fork.get("base_sha"):
        raise ValueError("Publication requires verified shared source ancestry")
    comparisons = source.get("workflow_only_differences", [])
    if len(comparisons) != 2 or {item.get("variant") for item in comparisons} != {
        "baseline",
        "candidate",
    }:
        raise ValueError("Publication requires both workflow-only source comparisons")
    workflow_path = report.get("inputs", {}).get("workflow_path")
    for comparison in comparisons:
        if comparison.get("revision") != fork.get(f"{comparison['variant']}_sha") or comparison.get(
            "paths"
        ) != [workflow_path]:
            raise ValueError("Source audit does not match the measured variant revisions")
    from ci_agent.experiments.live_loop import count_workflow_jobs, workflow

    baseline = (output / "baseline.yml").read_text(encoding="utf-8")
    expected = count_workflow_jobs(baseline, list(workflow(baseline)["jobs"]))
    raw_pairs = []
    for index in range(1, 4):
        raw_pair = {}
        for variant in ("baseline", "candidate"):
            receipts = [
                run for run in runs if run.get("pair") == index and run.get("variant") == variant
            ]
            if len(receipts) != 1:
                raise ValueError("Exactly one receipt is required for each matched variant")
            evidence = receipts[0].get("evidence", {})
            if evidence.get("head_sha") != fork.get(f"{variant}_sha"):
                raise ValueError("Run revision differs from audited source")
            raw_pair[variant] = evidence
        raw_pairs.append(raw_pair)
    recomputed = evaluate_experiment(raw_pairs, sealed.contract, expected_jobs=expected)
    if (
        recomputed["outcome"] != "win"
        or recomputed["verification"]["runner_labels_verified"] is not True
    ):
        raise ValueError(
            "Raw run evidence does not independently establish a publishable practical win"
        )
    from ci_agent.experiments.live_cache import compare_pair_caches

    for pair in raw_pairs:
        audits = []
        for variant in ("baseline", "candidate"):
            run_id = pair[variant]["id"]
            cache_path = output / f"cache-{run_id}.json"
            if not cache_path.exists():
                raise ValueError("Per-run cache evidence is missing")
            audit = json.loads(cache_path.read_text(encoding="utf-8"))
            if audit.get("run_id") != run_id:
                raise ValueError("Cache evidence identifies another run")
            audits.append(audit)
        if compare_pair_caches(*audits, expected_jobs=expected).get("matched") is not True:
            raise ValueError("Per-run cache evidence does not establish matched conditions")
    for field in ("pairs", "mean_reduction_percent", "exploratory_95_percent_interval"):
        if report.get(field) != recomputed[field]:
            raise ValueError("Saved timing summary differs from independent recomputation")
    urls = []
    run_ids = set()
    for receipt in runs:
        evidence = receipt.get("evidence", {})
        url = evidence.get("html_url", "")
        run_id = evidence.get("id")
        if (
            receipt.get("status") != "collected"
            or evidence.get("conclusion") != "success"
            or not url.startswith("https://github.com/")
            or not run_id
            or run_id in run_ids
        ):
            raise ValueError("Every published receipt must identify a distinct successful live run")
        run_ids.add(run_id)
        urls.append(f"- Pair {receipt['pair']} {receipt['variant']}: {url}")
    identity = client.authenticated_user()
    if str(identity.get("login", "")).casefold() != str(fork["owner"]).casefold():
        raise ValueError("Draft fork must belong to the authenticated user")
    repairs = report.get("inputs", {}).get("common_source_files", {})
    body = [
        (
            "Reduce PostgreSQL readiness polling idle time while preserving every CI job, "
            "matrix cell, command, and readiness probe."
        ),
        "",
        "Three measured matched pairs (summed runner minutes):",
        "",
        "| Pair | Baseline minutes | Candidate minutes | Reduction |",
        "| --- | ---: | ---: | ---: |",
    ]
    for index, pair in enumerate(pairs, 1):
        body.append(
            f"| {index} | {pair['baseline_minutes']:.3f} | "
            f"{pair['candidate_minutes']:.3f} | {pair['reduction_percent']:.2f}% |"
        )
    body += [
        "",
        f"Mean reduction: {report['mean_reduction_percent']:.2f}%.",
        f"Exploratory paired 95% interval: {report['exploratory_95_percent_interval']}.",
        (
            "The three-pair practical decision rule is not proof of statistical certainty. "
            "GitHub host load and cache hits are not proven equivalent."
        ),
        "",
        *urls,
        "",
        (
            "This draft compares the candidate against the experiment baseline branch. "
            "Both variants contain identical baseline source repairs; those repairs are "
            "excluded from this optimization diff."
        ),
    ]
    if repairs:
        body += [
            "",
            "Common baseline preparation: "
            + ", ".join(f"`{path}`" for path in sorted(repairs))
            + ".",
        ]
    report["publication_intent"] = {
        "owner": fork["owner"],
        "repository": fork["name"],
        "base": fork["baseline_branch"],
        "head": fork["candidate_branch"],
        "status": "pending",
    }
    report["publication"] = "Draft publication requested; reconcile if interrupted."
    save()
    try:
        pr = client.create_draft_pull_request(
            fork["owner"],
            fork["name"],
            head=fork["candidate_branch"],
            base=fork["baseline_branch"],
            title="ci: reduce PostgreSQL readiness polling idle time",
            body="\n".join(body),
        )
        url = pr.get("html_url")
        if not url:
            raise ValueError("GitHub draft response omitted its URL")
    except Exception:
        report["publication_intent"]["status"] = "unknown"
        report["publication"] = "Draft API outcome unknown; reconcile GitHub before retrying."
        save()
        raise
    report["draft_pr_url"] = url
    report["publication_intent"]["status"] = "created"
    report["publication"] = f"Draft PR created for human review: {url}"
    save()
    return report
