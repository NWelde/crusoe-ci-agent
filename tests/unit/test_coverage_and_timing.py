import pytest

from ci_agent.experiments.coverage import CoveragePlan
from ci_agent.experiments.shadow_mode import evaluate_shadow_pair
from ci_agent.experiments.timing import run_timing


def run(run_id, names):
    return {
        "id": run_id,
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-10-17T00:00:00Z",
        "run_started_at": "2026-10-17T00:00:10Z",
        "updated_at": "2026-10-17T00:01:00Z",
        "jobs": [
            {
                "id": run_id * 10 + i,
                "name": name,
                "conclusion": "success",
                "started_at": "2026-10-17T00:00:10Z",
                "completed_at": "2026-10-17T00:00:40Z",
            }
            for i, name in enumerate(names)
        ],
    }


def test_distinct_queue_execution_span_and_aggregate_runner_time():
    metrics = run_timing(run(1, ["a", "b"]))
    assert metrics["initial_queue_delay_s"] == 10
    assert metrics["job_execution_span_s"] == 30
    assert metrics["aggregate_runner_s"] == 60
    assert metrics["critical_path_s"] is None


def test_shadow_coverage_extension_accepts_unequal_job_counts_without_losing_required_identity():
    # This is evaluator capability, not executable sharding support. A strategy
    # must independently certify the partition before publication can use it.
    plan = CoveragePlan(
        baseline={"tests": ("a.py", "b.py")},
        candidate={"tests": (), "shard-1": ("a.py",), "shard-2": ("b.py",)},
        required_checks=("tests",),
    )
    result = evaluate_shadow_pair(run(1, ["tests"]), run(2, ["tests", "shard-1", "shard-2"]), plan)
    assert result["proposed_passed"]
    with pytest.raises(ValueError, match="coverage plan"):
        evaluate_shadow_pair(run(1, ["tests"]), run(2, ["tests", "shard-1"]), plan)


@pytest.mark.parametrize(
    "candidate",
    [
        {"tests": ("a.py",)},
        {"tests": ("a.py", "a.py", "b.py")},
        {"renamed-check": ("a.py", "b.py")},
    ],
)
def test_rejects_missing_duplicate_tests_and_changed_required_identity(candidate):
    with pytest.raises(ValueError):
        CoveragePlan({"tests": ("a.py", "b.py")}, candidate, ("tests",))


def test_renamed_check_cannot_win_even_when_job_counts_match():
    result = evaluate_shadow_pair(run(1, ["tests"]), run(2, ["not-tests"]), 1)
    assert result["outcome"] == "failure"
