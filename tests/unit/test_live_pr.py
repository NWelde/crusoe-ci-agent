import json
from unittest.mock import Mock

import pytest

from ci_agent.contracts import ContractReview, SealedContract, contract_fingerprint
from ci_agent.experiments.live_evaluation import evaluate_experiment
from ci_agent.models import RequiredCheck, SuccessContract
from ci_agent.reporting.live_pr import publish_verified_draft


def report(tmp_path):
    contract = SuccessContract(
        goal_id="goal",
        version=1,
        reviewed=True,
        required_checks=(RequiredCheck(name="tests", command="true"),),
    )
    sealed = SealedContract(
        contract=contract,
        contract_fingerprint=contract_fingerprint(contract),
        review=ContractReview(approved=True, rationale="Complete"),
    )
    (tmp_path / "baseline.yml").write_text(
        "jobs:\n  tests:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: 'true'\n"
    )
    result = {
        "cache_verification": {"matched": True, "pairs": [{"matched": True}] * 3},
        "status": "completed",
        "outcome": "win",
        "verification": {
            "distinct_runs": 6,
            "jobs_per_run": 187,
            "runner_labels_verified": True,
            "method": "independent raw-evidence recomputation",
        },
        "fork": {
            "owner": "team",
            "name": "fork",
            "baseline_branch": "baseline",
            "candidate_branch": "candidate",
            "baseline_sha": "baseline",
            "candidate_sha": "candidate",
            "base_sha": "common",
        },
        "pairs": [{"baseline_minutes": 100, "candidate_minutes": 90, "reduction_percent": 10}] * 3,
        "mean_reduction_percent": 10,
        "exploratory_95_percent_interval": [9, 11],
        "runs": [
            {
                "pair": index // 2 + 1,
                "variant": "baseline" if index % 2 == 0 else "candidate",
                "status": "collected",
                "evidence": {
                    "id": index + 1,
                    "status": "completed",
                    "head_sha": "baseline" if index % 2 == 0 else "candidate",
                    "conclusion": "success",
                    "html_url": f"https://github.com/team/fork/actions/runs/{index + 1}",
                    "jobs": [
                        {
                            "id": 100 + index,
                            "name": "tests",
                            "conclusion": "success",
                            "labels": ["ubuntu-24.04"],
                            "started_at": "2026-10-17T00:00:00Z",
                            "completed_at": "2026-10-17T00:01:00Z"
                            if index % 2 == 0
                            else "2026-10-17T00:00:30Z",
                        }
                    ],
                },
            }
            for index in range(6)
        ],
        "contract": sealed.model_dump(mode="json"),
        "inputs": {"workflow_path": ".github/workflows/ci.yml"},
        "source_verification": {
            "shared_source_sha": "common",
            "workflow_only_differences": [
                {"variant": variant, "revision": variant, "paths": [".github/workflows/ci.yml"]}
                for variant in ("baseline", "candidate")
            ],
        },
    }
    raw_pairs = [
        {
            "baseline": result["runs"][index]["evidence"],
            "candidate": result["runs"][index + 1]["evidence"],
        }
        for index in (0, 2, 4)
    ]
    result.update(evaluate_experiment(raw_pairs, contract, expected_jobs=1))
    for run in result["runs"]:
        run_id = run["evidence"]["id"]
        audit = {
            "run_id": run_id,
            "jobs": {
                "tests": {
                    "status": "exact_hit",
                    "requested_key_sha256": "same",
                    "restored_key_sha256": "same",
                }
            },
        }
        (tmp_path / f"cache-{run_id}.json").write_text(json.dumps(audit))
    return result


def client():
    value = Mock()
    value.authenticated_user.return_value = {"login": "team"}
    value.create_draft_pull_request.return_value = {
        "html_url": "https://github.com/team/fork/pull/1"
    }
    return value


def test_verified_draft_is_idempotent_and_targets_experiment_baseline(tmp_path):
    evidence, api = report(tmp_path), client()
    publish_verified_draft(api, evidence, tmp_path)
    publish_verified_draft(api, evidence, tmp_path)
    api.create_draft_pull_request.assert_called_once()
    options = api.create_draft_pull_request.call_args.kwargs
    assert options["base"] == "baseline"
    assert options["head"] == "candidate"
    assert "statistical certainty" in options["body"]
    assert options["body"].count("https://github.com/team/fork/actions/runs/") == 6
    assert json.loads((tmp_path / "report.json").read_text())["draft_pr_url"].endswith("/pull/1")


@pytest.mark.parametrize("mutation", ["loss", "incomplete", "runner", "foreign", "cache"])
def test_gate_rejects_ineligible_publication_without_write(tmp_path, mutation):
    evidence, api = report(tmp_path), client()
    if mutation == "loss":
        evidence["outcome"] = "loss"
    elif mutation == "incomplete":
        evidence["status"] = "stopped"
    elif mutation == "runner":
        evidence["verification"]["runner_labels_verified"] = False
    elif mutation == "cache":
        evidence["cache_verification"]["matched"] = False
    else:
        api.authenticated_user.return_value = {"login": "someone-else"}
    with pytest.raises(ValueError):
        publish_verified_draft(api, evidence, tmp_path)
    api.create_draft_pull_request.assert_not_called()


def test_ambiguous_api_write_cannot_be_retried_blindly(tmp_path):
    evidence, api = report(tmp_path), client()
    api.create_draft_pull_request.side_effect = TimeoutError("unknown response")
    with pytest.raises(TimeoutError):
        publish_verified_draft(api, evidence, tmp_path)
    persisted = json.loads((tmp_path / "report.json").read_text())
    assert persisted["publication_intent"]["status"] == "unknown"
    with pytest.raises(ValueError, match="reconcile"):
        publish_verified_draft(api, persisted, tmp_path)
    api.create_draft_pull_request.assert_called_once()


@pytest.mark.parametrize(
    "mutation", ["summary", "raw_loss", "missing_audit", "audit_revision", "seal"]
)
def test_raw_evidence_and_source_audit_cannot_be_bypassed(tmp_path, mutation):
    evidence, api = report(tmp_path), client()
    if mutation == "summary":
        evidence["pairs"][0]["reduction_percent"] = 99
    elif mutation == "raw_loss":
        evidence["runs"][1]["evidence"]["jobs"][0]["completed_at"] = "2026-10-17T00:02:00Z"
    elif mutation == "missing_audit":
        del evidence["source_verification"]
    elif mutation == "audit_revision":
        evidence["source_verification"]["workflow_only_differences"][0]["revision"] = "other"
    else:
        evidence["contract"]["contract"]["minimum_gain_percent"] = 0
    with pytest.raises(ValueError):
        publish_verified_draft(api, evidence, tmp_path)
    api.create_draft_pull_request.assert_not_called()
