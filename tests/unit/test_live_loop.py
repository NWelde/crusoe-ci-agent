import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from ci_agent.experiments.live_loop import evaluate_pair, run_live, validate_parallelism
from ci_agent.github.fork_experiment import prepare_fork_experiment
from ci_agent.github.runs import GitHubAPIError


def test_existing_fork_is_rejected_without_waiting_or_mutating(monkeypatch):
    from ci_agent.github import fork_experiment

    monkeypatch.setattr(fork_experiment, "_content_text", lambda _: BASE)
    client = Mock()
    client.authenticated_user.return_value = {"login": "team"}
    client.repository.return_value = {"default_branch": "master"}
    client.fork_repository.return_value = {"full_name": "team/already-existing"}
    progress = Mock()
    with pytest.raises(GitHubAPIError, match="existing fork"):
        prepare_fork_experiment(
            client,
            "owner/repo",
            ".github/workflows/ci.yml",
            CANDIDATE,
            run_key="test",
            on_progress=progress,
        )
    progress.assert_called_once()
    client.wait_for_repository.assert_not_called()
    client.set_actions_enabled.assert_not_called()


@pytest.mark.parametrize("existing_fork", [None, "team/existing"])
def test_fork_branches_use_inspected_source_despite_default_branch_drift(
    monkeypatch, existing_fork
):
    from ci_agent.github import fork_experiment

    monkeypatch.setattr(fork_experiment, "_content_text", lambda _: BASE)
    client = Mock()
    client.authenticated_user.return_value = {"login": "team"}
    client.repository.return_value = {
        "default_branch": "master",
        "full_name": "team/existing",
        "parent": {"full_name": "owner/repo"},
    }
    client.fork_repository.side_effect = lambda *_, name: {"full_name": f"team/{name}"}
    client.wait_for_repository.side_effect = lambda owner, name, **_: {
        "full_name": f"{owner}/{name}",
        "parent": {"full_name": "owner/repo"},
    }
    client.default_branch.return_value = ("master", "later-sha")
    client.get_contents.return_value = {"sha": "blob"}
    client.put_file.side_effect = [
        {"commit": {"sha": "baseline"}},
        {"commit": {"sha": "candidate"}},
    ]
    client.workflow.return_value = {"id": 1}
    fork = prepare_fork_experiment(
        client,
        "owner/repo",
        ".github/workflows/ci.yml",
        CANDIDATE,
        run_key="test",
        source_sha="inspected-sha",
        existing_fork=existing_fork,
    )
    assert fork.base_sha == "inspected-sha"
    assert all(call.args[-1] == "inspected-sha" for call in client.create_branch.call_args_list)
    if existing_fork:
        client.fork_repository.assert_not_called()
        client.set_actions_enabled.assert_not_called()


BASE = """name: CI
on: push
jobs:
  lint:
    runs-on: ubuntu-24.04
    steps:
      - run: bundle exec rubocop
  tests:
    needs: lint
    runs-on: ubuntu-24.04
    strategy:
      matrix:
        ruby: ['3.2', '3.3']
    steps:
      - run: bundle exec rake spec
"""
CANDIDATE = BASE.replace("    needs: lint\n", "")


def run(seconds=60, conclusion="success"):
    return {
        "status": "completed",
        "conclusion": conclusion,
        "head_sha": "sha",
        "jobs": [
            {
                "id": i,
                "name": name,
                "conclusion": conclusion,
                "started_at": "2026-10-17T00:00:00Z",
                "completed_at": f"2026-10-17T00:{seconds // 60:02}:{seconds % 60:02}Z",
            }
            for i, name in enumerate(["lint", "tests (3.2)", "tests (3.3)"])
        ],
    }


def test_parallelism_preserves_matrix_and_steps():
    assert validate_parallelism(BASE, CANDIDATE, ["lint", "tests"]) == 3


@pytest.mark.parametrize(
    "candidate",
    [
        CANDIDATE.replace("bundle exec rake spec", "echo passed"),
        CANDIDATE.replace("['3.2', '3.3']", "['3.2']"),
        CANDIDATE.replace("ubuntu-24.04", "ubuntu-latest"),
        BASE,
    ],
)
def test_unsafe_or_empty_changes_rejected(candidate):
    with pytest.raises(ValueError):
        validate_parallelism(BASE, candidate, ["lint", "tests"])


@pytest.mark.parametrize("mutation", ["failed", "missing", "duplicate", "renamed", "negative"])
def test_invalid_measurements_rejected(mutation):
    candidate = run()
    if mutation == "failed":
        candidate["jobs"][1]["conclusion"] = "failure"
    elif mutation == "missing":
        candidate["jobs"].pop()
    elif mutation == "duplicate":
        candidate["jobs"][1]["id"] = 0
    elif mutation == "renamed":
        candidate["jobs"][1]["name"] = "unrelated"
    else:
        candidate["jobs"][1]["started_at"] = "2026-10-18T00:00:00Z"
    with pytest.raises(ValueError):
        evaluate_pair(run(), candidate, 3)


def test_runner_minutes_sum_all_jobs():
    result = evaluate_pair(run(60), run(30), 3)
    assert result == {"baseline_minutes": 3, "candidate_minutes": 1.5, "reduction_percent": 50}


def setup_live(tmp_path, monkeypatch):
    from ci_agent.experiments import live_loop

    contract = SimpleNamespace(
        minimum_samples=3,
        max_run_pairs=3,
        max_experiment_minutes=10,
        minimum_gain_percent=5,
        metric="required_runner_minutes",
        allowed_optimizations=["parallelism"],
        required_checks=[
            SimpleNamespace(name="lint", command="bundle exec rubocop"),
            SimpleNamespace(name="tests", command="bundle exec rake spec"),
        ],
    )
    sealed = SimpleNamespace(
        contract=contract, contract_fingerprint="seal", model_dump=lambda **_: {"reviewed": True}
    )
    monkeypatch.setattr(live_loop, "load_contract", lambda _: sealed)
    monkeypatch.setattr(live_loop, "_content_text", lambda _: BASE)
    monkeypatch.setattr(live_loop, "verify_cache_conditions", lambda *args: None)
    fork = SimpleNamespace(
        owner="team",
        name="fork",
        workflow_id="ci",
        baseline_branch="baseline",
        candidate_branch="candidate",
        baseline_sha="sha",
        candidate_sha="sha",
        upstream="owner/repo",
        repository="team/fork",
        default_branch="master",
        base_sha="source-sha",
        workflow_path=".github/workflows/ci.yml",
    )
    prepare = Mock(return_value=fork)
    monkeypatch.setattr(live_loop, "prepare_fork_experiment", prepare)
    candidate = tmp_path / "candidate.yml"
    candidate.write_text(CANDIDATE)
    client = Mock()
    client.default_branch.return_value = ("master", "source-sha")
    client._get.return_value = {
        "status": "ahead",
        "files": [{"filename": ".github/workflows/ci.yml"}],
    }
    client.wait_for_dispatch_run.side_effect = [{"id": 123 + i} for i in range(6)]
    evidence = [copy.deepcopy(run(60 if i % 2 == 0 else 30)) for i in range(6)]
    for i, item in enumerate(evidence):
        item["id"] = 123 + i
    client.full_run.side_effect = evidence
    options = {
        "repository": "owner/repo",
        "workflow_path": ".github/workflows/ci.yml",
        "candidate_path": candidate,
        "contract_path": tmp_path / "contract.json",
        "output": tmp_path / "evidence",
        "run_key": "test",
    }
    return client, options, prepare


def test_live_coordinator_collects_three_pairs_and_independently_evaluates(tmp_path, monkeypatch):
    client, options, prepare = setup_live(tmp_path, monkeypatch)
    report = run_live(client, **options)
    assert len(report["pairs"]) == 3
    assert client.dispatch_workflow.call_count == 6
    assert report["outcome"] == "win"
    assert report["verification"]["distinct_runs"] == 6
    assert prepare.call_args.kwargs["source_sha"] == "source-sha"
    assert json.loads((options["output"] / "report.json").read_text())["status"] == "completed"
    with pytest.raises(FileExistsError):
        run_live(client, **options)
    assert client.dispatch_workflow.call_count == 6


def test_baseline_failure_stops_before_candidate_dispatch(tmp_path, monkeypatch):
    client, options, _ = setup_live(tmp_path, monkeypatch)
    client.full_run.side_effect = [run(conclusion="failure")]
    with pytest.raises(ValueError, match="Required checks failed"):
        run_live(client, **options)
    assert client.dispatch_workflow.call_count == 1
    report = json.loads((options["output"] / "report.json").read_text())
    assert report["outcome"] == "void"
    assert report["runs"][0]["run_id"] == 123


def test_resume_reuses_dispatched_run_and_finished_experiment(tmp_path, monkeypatch):
    client, options, prepare = setup_live(tmp_path, monkeypatch)
    client.wait_for_run_completion.side_effect = [OSError("connection lost")] + [None] * 6
    with pytest.raises(OSError):
        run_live(client, **options)
    assert client.dispatch_workflow.call_count == 1
    result = run_live(client, **options, resume=True)
    assert result["status"] == "completed"
    assert client.dispatch_workflow.call_count == 6
    prepare.assert_called_once()
    assert run_live(client, **options, resume=True) == result
    assert client.dispatch_workflow.call_count == 6


def test_resume_rejects_changed_inputs_without_dispatch(tmp_path, monkeypatch):
    client, options, _ = setup_live(tmp_path, monkeypatch)
    client.wait_for_run_completion.side_effect = OSError("connection lost")
    with pytest.raises(OSError):
        run_live(client, **options)
    with pytest.raises(ValueError, match="Resume inputs differ"):
        run_live(client, **(options | {"run_key": "changed"}), resume=True)
    assert client.dispatch_workflow.call_count == 1


def test_ambiguous_dispatch_is_never_repeated(tmp_path, monkeypatch):
    client, options, _ = setup_live(tmp_path, monkeypatch)
    client.wait_for_dispatch_run.side_effect = TimeoutError("unknown dispatch outcome")
    with pytest.raises(TimeoutError):
        run_live(client, **options)
    client.find_dispatch_run.return_value = []
    with pytest.raises(ValueError, match="Ambiguous pending dispatch"):
        run_live(client, **options, resume=True)
    assert client.dispatch_workflow.call_count == 1


@pytest.mark.parametrize("observed", ["win", "loss"])
def test_missing_cache_evidence_does_not_establish_causal_verdict(tmp_path, observed):
    from ci_agent.experiments.live_loop import verify_cache_conditions

    report = {"outcome": observed, "runs": []}
    verify_cache_conditions(Mock(), report, tmp_path, 3)
    assert report["outcome"] == "inconclusive"
    assert report["practical_outcome"] == observed
    assert report["cache_verification"]["matched"] is False


@pytest.mark.parametrize("candidate_passed", [True, False])
def test_shadow_coordinator_dispatches_one_pair_and_records_failure(
    tmp_path, monkeypatch, candidate_passed
):
    client, options, _ = setup_live(tmp_path, monkeypatch)
    baseline = run(60)
    candidate = run(30, conclusion="success" if candidate_passed else "failure")
    for index, evidence in enumerate((baseline, candidate)):
        evidence.update(
            id=123 + index,
            created_at="2026-10-17T00:00:00Z",
            run_started_at="2026-10-17T00:00:00Z",
            updated_at=f"2026-10-17T00:0{6 if index == 0 else 5}:00Z",
        )
    client.full_run.side_effect = [baseline, candidate]
    report = run_live(client, **options, evaluation_mode="shadow")
    assert client.dispatch_workflow.call_count == 2
    assert report["status"] == "completed"
    assert report["sample_pairs"] == 1
    assert report["outcome"] == ("speedup" if candidate_passed else "failure")
    assert report["verified_optimization"] is False


def test_preflight_rejection_makes_no_fork(tmp_path, monkeypatch):
    client, options, prepare = setup_live(tmp_path, monkeypatch)
    options["candidate_path"].write_text(CANDIDATE.replace("bundle exec rake spec", "echo ok"))
    with pytest.raises(ValueError):
        run_live(client, **options)
    prepare.assert_not_called()
    client.dispatch_workflow.assert_not_called()


def test_matrix_exclusions_are_counted():
    baseline = yaml.safe_load(BASE)
    baseline["jobs"]["tests"]["strategy"]["matrix"]["exclude"] = [{"ruby": "3.2"}]
    candidate = copy.deepcopy(baseline)
    candidate["jobs"]["tests"].pop("needs")
    assert (
        validate_parallelism(yaml.safe_dump(baseline), yaml.safe_dump(candidate), ["lint", "tests"])
        == 2
    )
