"""Local simulated experiment loop and judge-readable evidence export."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ci_agent.demo_adapters import DemoAdapters

GOAL = "Reduce CI runner minutes while keeping required checks enabled and passing."


class DemoRunConfig(BaseModel):
    """Optional local settings; the product goal itself remains fixed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required_checks: tuple[str, ...] = ("tests", "lint")
    sample_pairs: int = Field(default=3, ge=2)
    first_improvement: bool = True
    highlight_below_percent: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def checks_are_explicit(self) -> DemoRunConfig:
        if not self.required_checks:
            raise ValueError("at least one required check must be configured")
        if len(self.required_checks) != len(set(self.required_checks)):
            raise ValueError("required check names must be unique")
        return self


class DemoAdapter(Protocol):
    """Replaceable inputs for the runnable loop; schemas stay in this module."""

    label: str
    required_checks: tuple[str, ...]

    def observe(self) -> dict[str, object]: ...
    def propose(self) -> dict[str, object]: ...
    def validate(self, *, fail_check: bool = False) -> dict[str, object]: ...
    def compare(self, index: int, *, fail_check: bool = False) -> tuple[Any, Any]: ...


def run_demo(
    output: Path,
    *,
    adapters: DemoAdapter | None = None,
    config: DemoRunConfig | None = None,
    consecutive: bool = False,
    fail_check: bool = False,
) -> dict[str, Any]:
    """Run a deterministic simulated loop and save its complete event history."""
    config = config or DemoRunConfig()
    adapters = adapters or DemoAdapters(required_checks=config.required_checks)
    events: list[dict[str, Any]] = []

    def record(step: str, actor: str, rationale: str, details: dict[str, Any]) -> None:
        events.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "step": step,
                "actor_role": actor,
                "rationale": rationale,
                "details": details,
                "evidence_label": adapters.label,
                "prompt_version": "demo-v1" if actor in {"Planner", "Improver", "Verifier"} else None,
                "model": "none: deterministic demo adapter" if actor in {"Planner", "Improver", "Verifier"} else None,
            }
        )

    record("goal_loaded", "system", "The project has one fixed objective; no per-run goal prompt is needed.", {"goal": GOAL})
    record("success_rules_set", "Planner", "Lock the rules before inspecting candidate results.", {
        "primary_metric": "sum of required job runner minutes",
        "all_required_checks_enabled_and_passing": True,
        "first_improvement_minimum_reduction_percent": 5.0,
        "later_improvement_rule": "any real measured reduction",
        "highlight_below_percent": 1.0,
        "sample_pairs": config.sample_pairs,
        "real_improvement_rule": "all matched example pairs show a reduction; real evaluation needs a validated uncertainty method",
    })
    observed = adapters.observe()
    record("run_observed", "Observer", "The example run repeats package downloads, a possible runner-minute waste.", observed)
    proposal = adapters.propose()
    record("change_proposed", "Improver", str(proposal["hypothesis"]), proposal)
    validation = adapters.validate(fail_check=fail_check)
    record("change_checked", "Validator", str(validation["reason"]), validation)
    if not validation["safety_rules_passed"]:
        record("stopped", "system", "The proposed edit did not pass the safety rules.", {"stop_reason": "validation_failed"})
        return _write_report(output, events, "stopped", None, adapters.label)

    pairs: list[dict[str, Any]] = []
    for index in range(1, config.sample_pairs + 1):
        baseline, candidate = adapters.compare(index, fail_check=fail_check)
        pair = {
            "pair": index,
            "baseline": baseline.__dict__,
            "candidate": candidate.__dict__,
            "runner_minutes_saved": round(baseline.runner_minutes - candidate.runner_minutes, 3),
            "runner_minutes_reduction_percent": round(
                100 * (baseline.runner_minutes - candidate.runner_minutes) / baseline.runner_minutes, 2
            ),
        }
        pairs.append(pair)
        record("comparison_pair_completed", "Executor", "Run the original and changed examples under the same stated conditions.", pair)
        failed = [name for name in adapters.required_checks if candidate.checks.get(name) != "success"]
        if failed:
            record("stopped", "system", "A required check failed; runner-minute savings cannot make this a win.", {
                "failed_required_checks": failed,
                "candidate_run": candidate.run_id,
            })
            return _write_report(output, events, "stopped", {
                "outcome": "void",
                "reason": "required_check_failed",
                "required_checks_failed": failed,
                "run_pairs": pairs,
            }, adapters.label)

    mean_baseline = sum(p["baseline"]["runner_minutes"] for p in pairs) / len(pairs)
    mean_candidate = sum(p["candidate"]["runner_minutes"] for p in pairs) / len(pairs)
    reduction = 100 * (mean_baseline - mean_candidate) / mean_baseline
    every_pair_improves = all(p["runner_minutes_saved"] > 0 for p in pairs)
    threshold = 0.0 if consecutive or not config.first_improvement else 5.0
    qualifies = every_pair_improves and reduction >= threshold
    highlighted = reduction >= config.highlight_below_percent
    outcome = "win" if qualifies else ("inconclusive" if every_pair_improves else "loss")
    verdict = {
        "outcome": outcome,
        "primary_metric": "required_runner_minutes",
        "baseline_mean_runner_minutes": round(mean_baseline, 3),
        "candidate_mean_runner_minutes": round(mean_candidate, 3),
        "runner_minutes_saved": round(mean_baseline - mean_candidate, 3),
        "reduction_percent": round(reduction, 2),
        "required_checks_enabled_and_passed": True,
        "minimum_reduction_percent_for_this_demo": threshold,
        "all_three_pairs_improved": every_pair_improves,
        "highlight_in_summary": highlighted,
        "adoption_note": "Review maintenance and risk before adopting; measured improvement alone is not an automatic merge.",
        "evidence_limit": "SIMULATED example data; not evidence of real CI performance or statistical confidence.",
    }
    record("verdict_recorded", "Verifier", "Apply the saved rule to all pairs and required-check results.", verdict)
    return _write_report(output, events, outcome, {**verdict, "run_pairs": pairs}, adapters.label)


def _write_report(output: Path, events: list[dict[str, Any]], outcome: str,
                  verdict: dict[str, Any] | None, label: str) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    report = {"label": label, "status": outcome, "goal": GOAL, "events": events, "verdict": verdict}
    (output / "events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8"
    )
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    trace_lines = [
        "# Agent activity trace",
        "",
        f"> {label}",
        "",
        "This trace records observable actions, short decision summaries, and evidence. It does not contain private internal reasoning.",
        "",
        f"**Goal:** {GOAL}",
        "",
        f"**Status:** {outcome}",
        "",
        "## Timeline",
        "",
    ]
    for index, event in enumerate(events, 1):
        trace_lines.extend([
            f"### {index}. {event['step'].replace('_', ' ').title()}",
            "",
            f"- **Time (UTC):** {event['timestamp']}",
            f"- **Role:** {event['actor_role']}",
            f"- **Action summary:** {event['rationale']}",
            f"- **Evidence label:** {event['evidence_label']}",
        ])
        details = event.get("details")
        if details:
            trace_lines.extend(["", "**Observed details / evidence:**", "", "```json",
                                json.dumps(details, indent=2, sort_keys=True), "```"])
        trace_lines.append("")
    trace_lines.extend(["## Result", "", "```json",
                        json.dumps(verdict, indent=2, sort_keys=True) if verdict else "No verdict: stopped before evaluation.",
                        "```", ""])
    (output / "agent-trace.md").write_text("\n".join(trace_lines), encoding="utf-8")
    lines = ["# Simulated experiment report", "", f"> {label}", "", f"**Goal:** {GOAL}", "",
             f"**Outcome:** {outcome}", "", "## Decision history", ""]
    lines.extend(f"{i}. **{e['step']}** ({e['actor_role']}): {e['rationale']}" for i, e in enumerate(events, 1))
    lines.extend(["", "## Result", "", "```json", json.dumps(verdict, indent=2) if verdict else "No verdict: stopped before evaluation.", "```", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report
