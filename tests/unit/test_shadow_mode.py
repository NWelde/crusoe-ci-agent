import copy
from unittest.mock import Mock

import pytest

from ci_agent.experiments.shadow_mode import evaluate_shadow_pair
from ci_agent.reporting.shadow_pr import publish_shadow_draft

BASE = """name: CI
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - run: lint
  tests:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - run: tests
"""


def run(run_id, seconds, passed=True, revision="baseline-sha"):
    return {
        "id": run_id,
        "head_sha": revision,
        "status": "completed",
        "conclusion": "success" if passed else "failure",
        "created_at": "2026-10-17T00:00:00Z",
        "run_started_at": "2026-10-17T00:00:00Z",
        "updated_at": f"2026-10-17T00:{seconds // 60:02}:{seconds % 60:02}Z",
        "html_url": f"https://github.com/demo/fork/actions/runs/{run_id}",
        "jobs": [
            {"id": run_id * 10 + i, "name": name, "conclusion": "success" if passed else "failure"}
            for i, name in enumerate(("lint", "tests"))
        ],
    }


@pytest.mark.parametrize(
    ("before", "after", "candidate_passed", "outcome"),
    [
        (600, 500, True, "speedup"),
        (600, 590, True, "no_change"),
        (600, 700, True, "regression"),
        (600, 300, False, "failure"),
    ],
)
def test_shadow_matches_one_pair_elapsed_time_policy(before, after, candidate_passed, outcome):
    result = evaluate_shadow_pair(run(1, before), run(2, after, candidate_passed), 2)
    assert result["outcome"] == outcome
    assert result["sample_pairs"] == 1
    assert result["verified_optimization"] is False


def test_failed_baseline_is_inconclusive_and_missing_checks_cannot_win():
    assert evaluate_shadow_pair(run(1, 600, False), run(2, 300), 2)["outcome"] == "inconclusive"
    candidate = run(2, 300)
    candidate["jobs"].pop()
    assert evaluate_shadow_pair(run(1, 600), candidate, 2)["outcome"] == "failure"
    with pytest.raises(ValueError, match="distinct"):
        evaluate_shadow_pair(run(1, 600), run(1, 300), 2)


def setup_draft(tmp_path):
    (tmp_path / "baseline.yml").write_text(BASE)
    (tmp_path / "candidate.yml").write_text(BASE.replace("    needs: lint\n", ""))
    baseline, candidate = run(1, 600), run(2, 500, revision="candidate-sha")
    report = evaluate_shadow_pair(baseline, candidate, 2)
    report.update(
        status="completed",
        pairs=[copy.deepcopy(report)],
        inputs={"optimization": "parallelism"},
        fork={
            "owner": "demo",
            "name": "fork",
            "base_sha": "common-sha",
            "workflow_path": ".github/workflows/ci.yml",
            "baseline_branch": "baseline",
            "candidate_branch": "candidate",
            "baseline_sha": "baseline-sha",
            "candidate_sha": "candidate-sha",
        },
        runs=[
            {"pair": 1, "variant": "baseline", "evidence": baseline},
            {"pair": 1, "variant": "candidate", "evidence": candidate},
        ],
        additional_observations=[
            {"pair": 2, "variant": "candidate", "evidence": run(3, 700, False)}
        ],
        failed_checks=[{"name": "Later JRuby check", "failed_steps": ["spec"]}],
    )
    client = Mock()
    client.authenticated_user.return_value = {"login": "demo"}
    client._get.side_effect = lambda path: (
        {"status": "ahead", "files": [{"filename": ".github/workflows/ci.yml"}]}
        if "/compare/" in path
        else {"object": {"sha": path.rsplit("/", 1)[1] + "-sha"}}
    )
    client.create_draft_pull_request.return_value = {
        "html_url": "https://github.com/demo/fork/pull/1"
    }
    return report, client


def test_demo_draft_discloses_later_failures_and_is_idempotent(tmp_path):
    report, client = setup_draft(tmp_path)
    result = publish_shadow_draft(client, report, tmp_path)
    assert result["draft_pr_url"].endswith("/1")
    body = client.create_draft_pull_request.call_args.kwargs["body"]
    assert "Later JRuby check" in body
    assert "/actions/runs/3" in body
    assert "not a verified optimization" in body
    publish_shadow_draft(client, report, tmp_path)
    assert client.create_draft_pull_request.call_count == 1


def test_demo_rejects_moved_branch_and_forged_timing(tmp_path):
    report, client = setup_draft(tmp_path)
    report["saving_pct"] = 99
    with pytest.raises(ValueError, match="differs from raw"):
        publish_shadow_draft(client, report, tmp_path)
    client.create_draft_pull_request.assert_not_called()
    report["saving_pct"] = 100 / 6
    client._get.side_effect = lambda _: {
        "status": "ahead",
        "files": [{"filename": "lib/source.rb"}],
    }
    with pytest.raises(ValueError):
        publish_shadow_draft(client, report, tmp_path)
    client.create_draft_pull_request.assert_not_called()


def test_unknown_publication_outcome_is_not_retried(tmp_path):
    report, client = setup_draft(tmp_path)
    client.create_draft_pull_request.side_effect = OSError("connection dropped")
    with pytest.raises(OSError):
        publish_shadow_draft(client, report, tmp_path)
    with pytest.raises(ValueError, match="already attempted"):
        publish_shadow_draft(client, report, tmp_path)
    assert client.create_draft_pull_request.call_count == 1
