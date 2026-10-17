from copy import deepcopy
from types import SimpleNamespace

import pytest

from ci_agent.experiments.live_evaluation import evaluate_experiment


def evidence(candidate_seconds=30):
    pairs = []
    for index in range(3):
        pair = {}
        for offset, variant in enumerate(("baseline", "candidate")):
            seconds = 60 if variant == "baseline" else candidate_seconds
            pair[variant] = {
                "id": index * 2 + offset,
                "head_sha": variant,
                "status": "completed",
                "conclusion": "success",
                "jobs": [
                    {
                        "id": 100 + index * 2 + offset,
                        "name": "tests",
                        "conclusion": "success",
                        "labels": ["ubuntu-24.04"],
                        "started_at": "2026-10-17T00:00:00Z",
                        "completed_at": f"2026-10-17T00:{seconds // 60:02}:{seconds % 60:02}Z",
                    }
                ],
            }
        pairs.append(pair)
    return pairs


CONTRACT = SimpleNamespace(
    metric="required_runner_minutes", minimum_samples=3, max_run_pairs=3, minimum_gain_percent=5
)


@pytest.mark.parametrize("seconds,outcome", [(30, "win"), (59, "inconclusive"), (60, "loss")])
def test_independent_practical_verdict(seconds, outcome):
    result = evaluate_experiment(evidence(seconds), CONTRACT, expected_jobs=1)
    assert result["outcome"] == outcome
    assert result["verification"]["distinct_runs"] == 6
    assert result["verification"]["interval_is_exploratory"]


@pytest.mark.parametrize(
    "defect", ["reused_run", "revision", "failed", "labels", "coverage", "naive"]
)
def test_invalid_or_unmatched_evidence_fails_closed(defect):
    pairs = deepcopy(evidence())
    candidate = pairs[2]["candidate"]
    if defect == "reused_run":
        candidate["id"] = pairs[0]["candidate"]["id"]
    elif defect == "revision":
        candidate["head_sha"] = "drifted"
    elif defect == "failed":
        candidate["jobs"][0]["conclusion"] = "failure"
    elif defect == "labels":
        candidate["jobs"][0]["labels"] = ["windows-latest"]
    elif defect == "coverage":
        candidate["jobs"][0]["name"] = "unrelated"
    else:
        candidate["jobs"][0]["started_at"] = "2026-10-17T00:00:00"
    with pytest.raises(ValueError):
        evaluate_experiment(pairs, CONTRACT, expected_jobs=1)


def test_rejects_truncated_matrix_even_when_all_runs_match():
    with pytest.raises(ValueError, match="coverage"):
        evaluate_experiment(evidence(), CONTRACT, expected_jobs=2)


def test_rejects_partial_experiment():
    with pytest.raises(ValueError, match="three complete pairs"):
        evaluate_experiment(evidence()[:2], CONTRACT)
