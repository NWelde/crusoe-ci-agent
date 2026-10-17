"""Human-readable live execution evidence, including incomplete experiments."""

import json
from pathlib import Path


def _text(value):
    return str(value).replace("\n", " ").replace("|", "\\|")


def write_live_report(output, report, proposal_path=None):
    """Write report.md using only recorded receipts and measured observations."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    status = report.get("status", "unknown")
    completed = status == "completed"
    shadow = report.get("evaluation_mode") == "shadow"
    lines = [
        "# Live CI experiment",
        "",
        f"Execution status: **{_text(status)}**. Outcome: **{_text(report.get('outcome', 'pending'))}**.",
        "",
        (
            "One-pair Shadow Runner demo comparison completed."
            if shadow
            else "The full end-to-end measurement completed."
        )
        if completed
        else "The end-to-end measurement has not completed; this is partial execution evidence.",
    ]
    if report.get("reason"):
        lines += ["", f"Reason: {_text(report['reason'])}"]
    if report.get("failed_checks"):
        lines += [
            "",
            "## Known failed required checks" if shadow else "## Failed required checks",
            "",
        ]
        for check in report["failed_checks"]:
            steps = check.get("failed_steps", [])
            step_names = [
                step.get("name", "unnamed step") if isinstance(step, dict) else str(step)
                for step in steps
            ]
            detail = (
                "; failed steps: " + ", ".join(_text(step) for step in step_names)
                if step_names
                else ""
            )
            lines.append(
                f"- {_text(check.get('name', 'unnamed job'))} "
                f"(job {_text(check.get('job_id', 'unknown'))}): "
                f"**{_text(check.get('conclusion', 'unknown'))}**{detail}."
            )
        lines += [
            "",
            (
                "Known failures remain unresolved. This draft is for review and is not a verified win."
                if shadow
                else "A required-check failure invalidates this experiment; it cannot be published as a verified win."
            ),
        ]
    inputs = report.get("inputs", {})
    fork = report.get("fork", {})
    lines += [
        "",
        f"Repository: `{_text(inputs.get('repository', fork.get('upstream', 'unknown')))}`.",
        f"Optimization: `{_text(inputs.get('optimization', 'unknown'))}`.",
        f"Source revision: `{_text(report.get('upstream_source_sha', 'not recorded'))}`.",
    ]
    prepared = inputs.get("common_source_files", {})
    if prepared:
        lines += ["", "Baseline preparation applied identically to both variants:", ""]
        lines += [f"- `{_text(path)}`" for path in sorted(prepared)]
        lines += [
            "",
            "These repairs establish the measured baseline and are separate from the optimization.",
        ]
    if proposal_path:
        proposal_path = Path(proposal_path)
        if proposal_path.exists():
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review = proposal.get("review", {})
            lines += [
                "",
                f"Proposal review approved: **{review.get('approved', False)}**.",
                f"Proposal evidence: `{_text(proposal_path.resolve())}`.",
            ]
    lines += [
        "",
        "## GitHub run receipts",
        "",
        "| Pair | Variant | Run | Receipt | Conclusion | Measured jobs |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for receipt in report.get("runs", []) + report.get("additional_observations", []):
        run = receipt.get("evidence", {})
        run_id = run.get("id", receipt.get("run_id"))
        url = run.get("html_url")
        link = f"[{run_id}]({url})" if url else str(run_id or "not observed")
        lines.append(
            f"| {_text(receipt.get('pair', '?'))} | {_text(receipt.get('variant', '?'))} "
            f"| {link} | {_text(receipt.get('status', '?'))} "
            f"| {_text(run.get('conclusion', 'pending'))} | {len(run.get('jobs', []))} |"
        )
    if report.get("pairs"):
        if shadow:
            pair = report["pairs"][0]
            lines += [
                "",
                "## One-pair elapsed-time observation",
                "",
                f"Baseline: {pair['baseline_duration_s']:.1f}s. Candidate: {pair['proposed_duration_s']:.1f}s.",
                f"Observed reduction: {pair['saving_pct']:.2f}%.",
                "Single-pair demo evidence; no statistical-confidence or verified-optimization claim.",
            ]
        else:
            _append_research_pairs(lines, report)
    if completed and "mean_reduction_percent" in report:
        lines += ["", f"Mean measured reduction: **{report['mean_reduction_percent']:.2f}%**."]
        interval = report.get("exploratory_95_percent_interval")
        if interval:
            lines += [f"Exploratory paired 95% interval: {interval[0]:.2f}% to {interval[1]:.2f}%."]
    verification = report.get("verification", {})
    if verification:
        lines += [
            "",
            "## Independent verification",
            "",
            f"Method: {_text(verification.get('method', 'unknown'))}.",
            f"Distinct runs: {verification.get('distinct_runs', 'unknown')}; jobs per run: {verification.get('jobs_per_run', 'unknown')}; runner labels verified: {verification.get('runner_labels_verified', False)}.",
        ]
        lines += ["", *[f"- {_text(item)}" for item in verification.get("limitations", [])]]
    lines += [
        "",
        (
            "Demo policy: one pair; cache and host conditions remain uncontrolled."
            if shadow
            else "Three pairs implement a practical decision rule; they do not establish statistical certainty."
        ),
        "",
        _text(report.get("publication", "Publication has not occurred.")),
        "",
    ]
    target = output / "report.md"
    temporary = output / "report.md.tmp"
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(target)
    return target


def _append_research_pairs(lines, report):
    lines += [
        "",
        "## Measured pairs",
        "",
        "| Pair | Baseline runner minutes | Candidate runner minutes | Reduction |",
        "| --- | ---: | ---: | ---: |",
    ]
    for index, pair in enumerate(report["pairs"], 1):
        lines.append(
            f"| {index} | {pair['baseline_minutes']:.3f} "
            f"| {pair['candidate_minutes']:.3f} | {pair['reduction_percent']:.2f}% |"
        )
