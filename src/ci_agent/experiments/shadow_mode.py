"""Demo comparison policy: one real pair, elapsed time, explicit check results."""

from datetime import datetime

from ci_agent.experiments.coverage import coverage_signature, expected_count
from ci_agent.experiments.timing import run_timing


def evaluate_shadow_pair(baseline, candidate, expected_jobs):
    if not baseline.get("id") or not candidate.get("id") or baseline["id"] == candidate["id"]:
        raise ValueError("Two distinct real run IDs are required")
    durations = []
    checks = []
    for variant, run in (('baseline', baseline), ('candidate', candidate)):
        if run.get("status") != "completed":
            raise ValueError("Shadow comparison requires completed runs")
        start = datetime.fromisoformat(run.get("run_started_at") or run["created_at"])
        end = datetime.fromisoformat(run["updated_at"])
        seconds = (end - start).total_seconds()
        if start.tzinfo is None or end.tzinfo is None or seconds <= 0:
            raise ValueError("Invalid elapsed-time evidence")
        durations.append(seconds)
        jobs = run.get("jobs", [])
        checks.append(
            run.get("conclusion") == "success"
            and len(jobs) == expected_count(expected_jobs, variant)
            and len({j["id"] for j in jobs}) == len(jobs)
            and all(j.get("conclusion") == "success" for j in jobs)
        )
    saved = durations[0] - durations[1]
    if coverage_signature(baseline.get('jobs', []), expected_jobs, 'baseline') != coverage_signature(
        candidate.get('jobs', []), expected_jobs, 'candidate'):
        checks[1] = False
    percent = saved / durations[0] * 100
    outcome = (
        "inconclusive"
        if not checks[0]
        else "failure"
        if not checks[1]
        else "speedup"
        if percent >= 5
        else "regression"
        if percent <= -5
        else "no_change"
    )
    return {
        "outcome": outcome,
        "baseline_duration_s": durations[0],
        "proposed_duration_s": durations[1],
        "saving_s": saved,
        "saving_pct": percent,
        "baseline_passed": checks[0],
        "proposed_passed": checks[1],
        "evaluation_mode": "shadow",
        "metric": "workflow_elapsed_seconds",
        "sample_pairs": 1,
        "verified_optimization": False,
        "timing": {"baseline": run_timing(baseline), "candidate": run_timing(candidate)},
        "evidence_limit": "Single-pair demo observation; cache and host conditions are uncontrolled.",
    }
