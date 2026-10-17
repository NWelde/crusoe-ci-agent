import json

from click.testing import CliRunner

from ci_agent.cli import main


def test_demo_runs_all_steps_and_exports_auditable_simulated_history(tmp_path):
    output = tmp_path / "demo"
    result = CliRunner().invoke(main, ["demo-loop", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert "SIMULATED" in result.output
    assert "Verdict: win" in result.output
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"]["primary_metric"] == "required_runner_minutes"
    assert report["verdict"]["reduction_percent"] == 8.0
    steps = [event["step"] for event in report["events"]]
    assert steps == [
        "goal_loaded", "success_rules_set", "run_observed", "change_proposed",
        "change_checked", "comparison_pair_completed", "comparison_pair_completed",
        "comparison_pair_completed", "verdict_recorded",
    ]
    assert all(event["evidence_label"].startswith("SIMULATED") for event in report["events"])
    assert (output / "events.jsonl").is_file()
    assert (output / "report.md").is_file()


def test_demo_stops_when_a_required_check_fails(tmp_path):
    output = tmp_path / "failed-demo"
    result = CliRunner().invoke(
        main, ["demo-loop", "--fail-check", "--output", str(output)]
    )

    assert result.exit_code == 0, result.output
    assert "Status: stopped" in result.output
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"]["outcome"] == "void"
    assert report["verdict"]["required_checks_failed"] == ["tests"]
    assert report["events"][-1]["step"] == "stopped"
    assert not any(event["step"] == "verdict_recorded" for event in report["events"])


def test_demo_accepts_a_measured_small_gain_for_a_later_change(tmp_path):
    result = CliRunner().invoke(
        main, ["demo-loop", "--consecutive", "--output", str(tmp_path / "later")]
    )
    assert result.exit_code == 0, result.output
    assert "Verdict: win" in result.output


def test_live_mode_fails_instead_of_falling_back_to_simulated_adapters(tmp_path):
    result = CliRunner().invoke(
        main, ["demo-loop", "--live", "--output", str(tmp_path / "live")]
    )
    assert result.exit_code != 0
    assert "Live adapters are not implemented" in result.output
    assert "No simulated adapter was used" in result.output
    assert not (tmp_path / "live").exists()


def test_demo_reads_required_checks_and_sample_count_from_config(tmp_path):
    config = tmp_path / "demo.json"
    config.write_text(
        '{"required_checks":["tests"],"sample_pairs":2,'
        '"first_improvement":false,"highlight_below_percent":1.0}',
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        main,
        ["demo-loop", "--config", str(config), "--output", str(tmp_path / "configured")],
    )
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / "configured" / "report.json").read_text(encoding="utf-8"))
    assert len(report["verdict"]["run_pairs"]) == 2
    assert report["verdict"]["minimum_reduction_percent_for_this_demo"] == 0.0
