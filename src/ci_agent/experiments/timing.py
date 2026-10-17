"""Distinct observed timing quantities; unavailable evidence remains null."""

from datetime import datetime


def run_timing(run):
    def stamp(value):
        if not value:
            return None
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError("Timing evidence must be timezone aware")
        return result

    created, started = stamp(run.get("created_at")), stamp(run.get("run_started_at"))
    queue = (started - created).total_seconds() if created and started else None
    intervals = [
        (stamp(j.get("started_at")), stamp(j.get("completed_at"))) for j in run.get("jobs", [])
    ]
    complete = bool(intervals) and all(a and b for a, b in intervals)
    if complete and any(b < a for a, b in intervals):
        raise ValueError("Negative job duration")
    if queue is not None and queue < 0:
        raise ValueError("Negative initial queue delay")
    return {
        "initial_queue_delay_s": queue,
        "job_execution_span_s": (
            max(b for a, b in intervals) - min(a for a, b in intervals)
        ).total_seconds()
        if complete
        else None,
        "aggregate_runner_s": sum((b - a).total_seconds() for a, b in intervals)
        if complete
        else None,
        "critical_path_s": None,
        "limitation": "Job execution span includes inter-job waiting; exact DAG critical path and per-job queue delay are unavailable.",
    }
