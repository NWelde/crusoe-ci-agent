"""Re-evaluate earliest existing evidence without rerunning Actions or hiding repeats."""

import json

from ci_agent.experiments.live_loop import count_workflow_jobs, workflow
from ci_agent.experiments.shadow_mode import evaluate_shadow_pair
from ci_agent.reporting.live_report import write_live_report


def create_shadow_report(evidence, output):
    source = json.loads(evidence.read_text(encoding="utf-8"))
    receipts = source["runs"]
    first = min(r["pair"] for r in receipts)
    selected = [r for r in receipts if r["pair"] == first]
    if len(selected) != 2 or {r["variant"] for r in selected} != {"baseline", "candidate"}:
        raise ValueError("Earliest pair must have two complete receipts")
    baseline_path = evidence.parent / "baseline.yml"
    baseline = baseline_path.read_text(encoding="utf-8")
    expected = count_workflow_jobs(baseline, list(workflow(baseline)["jobs"]))
    raw = {r["variant"]: r["evidence"] for r in selected}
    result = evaluate_shadow_pair(raw["baseline"], raw["candidate"], expected)
    report = {k: source[k] for k in ("fork", "inputs", "contract", "upstream_source_sha")}
    report.update(
        result,
        status="completed",
        evidence_class="LIVE_SINGLE_PAIR_DEMO",
        runs=selected,
        pairs=[result],
        additional_observations=[r for r in receipts if r["pair"] != first],
        failed_checks=source.get("failed_checks", []),
        source_verification=source.get("source_verification"),
        original_report=str(evidence.resolve()),
        original_outcome=source.get("outcome"),
        measurement_policy="Explicit demo override: one pair and elapsed time. Original sealed measurement policy remains unchanged.",
        publication="Demo report only; no PR created yet.",
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "baseline.yml").write_text(baseline, encoding="utf-8")
    candidate = evidence.parent / "candidate.yml"
    (output / "candidate.yml").write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_live_report(output, report)
    return report
