import json

import pytest
from pydantic import ValidationError

from ci_agent.config import AgentConfig
from ci_agent.models import (
    Experiment,
    JobSnapshot,
    Proposal,
    RequiredCheck,
    RunMeasurement,
    RunPair,
    RunSnapshot,
    RunVariant,
    SuccessContract,
    Verdict,
)


def make_run(run_id: str, *, fixture: bool = False) -> RunSnapshot:
    return RunSnapshot(
        repository_id="repo-1",
        workflow_id="workflow-1",
        github_run_id=run_id,
        source_revision="abc123",
        status="completed",
        conclusion="success",
        created_at="2026-10-17T12:00:00Z",
        is_fixture=fixture,
        jobs=(
            JobSnapshot(
                id="job-1",
                name="tests",
                status="completed",
                conclusion="success",
                duration_seconds=42,
            ),
        ),
    )


def test_snapshot_serializes_and_reloads_consistently():
    run = make_run("100")
    payload = run.model_dump_json()
    assert RunSnapshot.model_validate_json(payload) == run
    assert json.loads(payload)["schema_version"] == 1


def test_success_contract_requires_checks_and_feasible_sample_count():
    with pytest.raises(ValidationError, match="at least one required check"):
        SuccessContract(goal_id="goal-1", version=1, required_checks=())
    with pytest.raises(ValidationError, match="requires exactly"):
        SuccessContract(
            goal_id="goal-1",
            version=1,
            required_checks=(RequiredCheck(name="tests"),),
            minimum_samples=2,
            max_run_pairs=3,
        )


def test_later_success_contract_can_use_any_real_positive_improvement():
    contract = SuccessContract(
        goal_id="goal-1",
        version=2,
        required_checks=(RequiredCheck(name="tests"),),
        is_first_improvement=False,
        minimum_gain_percent=0,
    )
    assert contract.highlight_below_percent == 1.0
    with pytest.raises(ValidationError, match="later improvements require"):
        SuccessContract(
            goal_id="goal-1",
            version=2,
            required_checks=(RequiredCheck(name="tests"),),
            is_first_improvement=False,
            minimum_gain_percent=5.0,
        )


def test_proposal_computes_and_checks_patch_fingerprint():
    proposal = Proposal(
        experiment_id="exp-1",
        hypothesis="Cache packages",
        optimization_type="caching",
        patch="+ cache",
        expected_effect="Faster installs",
        affected_paths=(".github/workflows/ci.yml",),
    )
    assert len(proposal.patch_fingerprint) == 64
    with pytest.raises(ValidationError, match="does not match patch content"):
        Proposal(
            experiment_id="exp-1",
            hypothesis="Cache packages",
            optimization_type="caching",
            patch="+ cache",
            patch_fingerprint="bad",
            expected_effect="Faster installs",
            affected_paths=("ci.yml",),
        )


def test_run_pair_rejects_fixture_and_real_run_mix():
    common = {
        "experiment_id": "exp-1",
        "runner": "ubuntu-latest",
        "required_checks_passed": True,
    }
    baseline = RunMeasurement(
        variant=RunVariant.BASELINE,
        pair_index=1,
        run=make_run("100"),
        wall_clock_seconds=120,
        runner_seconds=130,
        **common,
    )
    candidate = RunMeasurement(
        variant=RunVariant.CANDIDATE,
        pair_index=1,
        run=make_run("101", fixture=True),
        wall_clock_seconds=100,
        runner_seconds=105,
        is_fixture=True,
        **common,
    )
    with pytest.raises(ValidationError, match="cannot compare a fixture run with a real run"):
        RunPair(experiment_id="exp-1", pair_index=1, baseline=baseline, candidate=candidate)


def test_experiment_requires_a_hypothesis():
    with pytest.raises(ValidationError):
        Experiment(
            goal_id="g",
            contract_id="c",
            repository_id="r",
            workflow_id="w",
            source_revision="sha",
            workflow_fingerprint="wf",
            comparison_key="key",
        )


def test_verdict_vocabulary_and_safe_defaults():
    assert {v.value for v in Verdict} == {"win", "loss", "void", "inconclusive"}
    config = AgentConfig()
    assert config.required_checks
    assert config.minimum_samples == config.max_run_pairs_per_experiment == 3
    assert config.minimum_gain_percent == 5.0
    assert config.allow_fixture_runs is False
