import json
from pathlib import Path

import pytest


REPORT = Path("artifacts/bro-15-integration/report.json")


@pytest.fixture(scope="module")
def report():
    if not REPORT.exists():
        pytest.skip("Run scripts/run_demo.ps1 to generate BRO-15 integration evidence.")
    return json.loads(REPORT.read_text(encoding="utf-8-sig"))


def test_report_is_pinned_and_does_not_claim_live_performance(report):
    assert report["status"] == "passed"
    assert report["evidence_class"] == "LOCAL_REPLAY_AND_TARGET_CHECKS"
    assert report["repository"] == "madeintandem/jsonb_accessor"
    assert report["target_revision"] == "12d057cbe2da23ac87368266504681ff1ce62e0b"
    assert report["no_github_actions_dispatched"] is True
    assert report["no_pull_request_created"] is True
    assert report["no_live_performance_claim"] is True


def test_report_has_reproducible_target_and_patch_gate_results(report):
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["target_locked_test_suite"]["status"] == "passed"
    assert checks["legitimate_cache_patch"]["status"] == "passed"
    assert checks["shortcut_patch_rejection"]["status"] == "passed"
    assert checks["out_of_scope_patch_rejection"]["status"] == "passed"
    assert checks["mismatched_revision_void_gate"]["status"] == "passed"


def test_report_does_not_hide_missing_live_adapters(report):
    gaps = " ".join(report["unimplemented_or_unverified"])
    assert "No GitHub Actions workflow was dispatched" in gaps
    assert "durable experiment state machine" in gaps
    assert "restart/resume duplication" in gaps


def test_checklist_labels_unimplemented_gates_honestly(report):
    checklist = " ".join(report["acceptance_checklist"])
    assert "evaluator is not implemented" in checklist
    assert "PR publication gate is not implemented" in checklist
    assert all(check["status"] == "passed" for check in report["checks"])


def test_report_records_fixture_patch_outcomes(report):
    fixtures = {entry["fixture"]: entry for entry in report["fixtures"]}
    assert fixtures["cache-pip.patch"]["observed_eligible"] is True
    assert fixtures["remove-tests.patch"]["observed_eligible"] is False
    assert "required_check_removed" in fixtures["remove-tests.patch"]["rejection_reasons"]
    assert fixtures["out-of-scope.patch"]["observed_eligible"] is False
    assert "out_of_scope_paths_changed" in fixtures["out-of-scope.patch"]["rejection_reasons"]


def test_simulated_cli_loop_retains_simulated_label(report):
    success = Path("artifacts/bro-15-integration/simulated-success/report.json")
    assert success.exists()
    simulated = json.loads(success.read_text(encoding="utf-8"))
    assert simulated["label"].startswith("SIMULATED")
    assert simulated["verdict"]["outcome"] == "win"
