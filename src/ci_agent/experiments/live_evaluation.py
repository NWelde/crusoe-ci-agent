"""Recompute a live experiment verdict from raw GitHub evidence, independently."""

import math
import statistics
from datetime import datetime

from ci_agent.experiments.coverage import coverage_signature, expected_count, runner_signature


def evaluate_experiment(pairs, contract, expected_jobs=None):
    """Apply the sealed three-pair policy; never trust coordinator timing summaries.

    Each pair contains ``baseline`` and ``candidate`` full GitHub run payloads.
    This verifies observations, not causal certainty or cache-hit equivalence.
    Invalid observations raise ValueError rather than producing a winning verdict.
    """
    if contract.metric != "required_runner_minutes" or contract.minimum_samples != 3:
        raise ValueError("Independent evaluation requires the three-pair runner-minute policy")
    if len(pairs) != 3 or contract.max_run_pairs != 3:
        raise ValueError("Exactly three complete pairs are required")
    seen_runs = set()
    coverage = None
    revisions = {}
    results = []
    missing_labels = False
    job_counts = {}
    for pair in pairs:
        totals = []
        runner_labels = []
        for variant in ("baseline", "candidate"):
            run = pair[variant]
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                raise ValueError("Every run must complete successfully")
            run_id = run.get("id")
            if run_id is None or run_id in seen_runs:
                raise ValueError("Six distinct GitHub run IDs are required")
            seen_runs.add(run_id)
            revision = run.get("head_sha")
            if not revision or revisions.setdefault(variant, revision) != revision:
                raise ValueError("Each variant must use one immutable source revision")
            jobs = run.get("jobs", [])
            job_counts[variant] = len(jobs)
            if not jobs or (expected_jobs is not None and len(jobs) != expected_count(expected_jobs, variant)):
                raise ValueError("Full expected job coverage is required")
            if len({job.get("id") for job in jobs}) != len(jobs):
                raise ValueError("Duplicate job IDs in run evidence")
            names = coverage_signature(jobs, expected_jobs, variant)
            if None in names or (coverage is not None and names != coverage):
                raise ValueError("Job coverage differs across the six runs")
            coverage = names
            duration = 0
            labels = []
            for job in jobs:
                if (
                    job.get("status", "completed") != "completed"
                    or job.get("conclusion") != "success"
                ):
                    raise ValueError("Every measured job must complete successfully")
                try:
                    start = datetime.fromisoformat(job["started_at"])
                    end = datetime.fromisoformat(job["completed_at"])
                    seconds = (end - start).total_seconds()
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("Invalid job timing evidence") from exc
                if (
                    start.tzinfo is None
                    or end.tzinfo is None
                    or not math.isfinite(seconds)
                    or seconds < 0
                ):
                    raise ValueError("Job timestamps must be ordered and timezone aware")
                duration += seconds
                if not job.get("labels"):
                    missing_labels = True
                labels.append((job["name"], tuple(sorted(job.get("labels", [])))))
            if duration <= 0:
                raise ValueError("Total runner duration must be positive")
            totals.append(duration / 60)
            runner_labels.append(runner_signature(jobs, expected_jobs, variant))
        if runner_labels[0] != runner_labels[1]:
            raise ValueError("Baseline and candidate runner labels differ")
        results.append(
            {
                "baseline_minutes": totals[0],
                "candidate_minutes": totals[1],
                "reduction_percent": 100 * (totals[0] - totals[1]) / totals[0],
            }
        )
    reductions = [pair["reduction_percent"] for pair in results]
    mean = statistics.mean(reductions)
    margin = 4.302652729911275 * statistics.stdev(reductions) / math.sqrt(3)
    outcome = (
        "win"
        if min(reductions) > 0 and mean >= contract.minimum_gain_percent
        else "inconclusive"
        if min(reductions) > 0
        else "loss"
    )
    return {
        "outcome": outcome,
        "pairs": results,
        "mean_reduction_percent": mean,
        "exploratory_95_percent_interval": [mean - margin, mean + margin],
        "verification": {
            "method": "independent raw-evidence recomputation",
            "distinct_runs": len(seen_runs),
            "jobs_per_run": job_counts["baseline"],
            "jobs_per_variant": job_counts,
            "coverage_units": sum(coverage.values()),
            "runner_labels_verified": not missing_labels,
            "interval_is_exploratory": True,
            "limitations": [
                "Three pairs do not establish statistical certainty.",
                "GitHub host load and cache hits are not proven equivalent.",
            ],
        },
    }
