from ci_agent.models import (
    Experiment,
    ExperimentStatus,
    RequiredCheck,
    SharedGoal,
    SuccessContract,
    Verdict,
    VerdictRecord,
)
from ci_agent.storage import SQLiteExperimentStore


def make_records():
    goal = SharedGoal(workflow_id="workflow-1")
    contract = SuccessContract(
        goal_id=goal.id,
        version=1,
        required_checks=(RequiredCheck(name="tests"),),
    )
    experiment = Experiment(
        goal_id=goal.id,
        contract_id=contract.id,
        repository_id="repo-1",
        workflow_id=goal.workflow_id,
        source_revision="abc123",
        workflow_fingerprint="workflow-hash",
        comparison_key="comparison-1",
        status=ExperimentStatus.RUNNING,
        hypothesis="Cache dependencies to reduce install time.",
    )
    return goal, contract, experiment


def test_records_survive_reopening_the_database(tmp_path):
    database = tmp_path / "state" / "experiments.sqlite3"
    goal, contract, experiment = make_records()

    store = SQLiteExperimentStore(database)
    store.save_goal(goal)
    store.save_contract(contract)
    store.save_experiment(experiment)

    reopened = SQLiteExperimentStore(database)
    assert reopened.get_goal(goal.id) == goal
    assert reopened.get_contract(contract.id) == contract
    assert reopened.get_experiment(experiment.id) == experiment
    assert reopened.get_experiment_by_comparison_key("comparison-1") == experiment


def test_event_and_verdict_duplicates_are_ignored(tmp_path):
    database = tmp_path / "experiments.sqlite3"
    goal, contract, experiment = make_records()
    store = SQLiteExperimentStore(database)
    store.save_goal(goal)
    store.save_contract(contract)
    store.save_experiment(experiment)

    assert store.save_event("event-1", experiment.id, "running", "Started") is True
    assert store.save_event("event-1", experiment.id, "running", "Started") is False
    assert len(store.list_events(experiment.id)) == 1
    assert store.list_experiments(
        workflow_id=goal.workflow_id,
        statuses=(ExperimentStatus.RUNNING,),
    ) == (experiment,)

    verdict = VerdictRecord(
        experiment_id=experiment.id,
        contract_id=contract.id,
        outcome=Verdict.LOSS,
        evidence_fingerprint="evidence-1",
        method_version="v1",
        sample_count=3,
        explanation="The candidate did not improve the measured result.",
    )
    assert store.save_verdict(verdict) is True
    assert store.save_verdict(verdict) is False
    assert store.list_verdicts(experiment.id) == (verdict,)
