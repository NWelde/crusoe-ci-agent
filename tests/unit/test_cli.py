from click.testing import CliRunner

from ci_agent.cli import main


def test_local_smoke_requires_no_credentials():
    result = CliRunner().invoke(main, ["smoke"])
    assert result.exit_code == 0
    assert "Local SQLite smoke check passed" in result.output


def test_live_e2e_wires_reviewed_setup_to_pinned_execution(monkeypatch, tmp_path):
    from unittest.mock import Mock

    from ci_agent.experiments import live_setup

    setup = Mock(return_value={"sha": "pinned-sha", "workflow_path": ".github/workflows/ci.yml"})
    execute = Mock(return_value={"outcome": "loss", "status": "completed"})
    monkeypatch.setattr(live_setup, "prepare_e2e", setup)
    monkeypatch.setattr("ci_agent.cli.run_live", execute)
    monkeypatch.setattr("ci_agent.cli.GitHubClient.from_git_credential", lambda: "client")
    args = ["live-e2e", "--fork-repository", "team/fork", "--output", str(tmp_path / "run")]
    blocked = CliRunner().invoke(main, args)
    assert blocked.exit_code != 0
    setup.assert_not_called()
    proposal = tmp_path / 'run' / 'setup' / 'proposal'
    proposal.mkdir(parents=True)
    (proposal / 'proposal.json').write_text('{"proposal": {"optimization": "service_readiness"}}')
    result = CliRunner().invoke(main, args + ["--confirm-live-runs"])
    assert result.exit_code == 0, result.output
    assert "Outcome: loss" in result.output
    assert execute.call_args.kwargs["source_revision"] == "pinned-sha"
    assert execute.call_args.kwargs["optimization"] == "service_readiness"
    assert execute.call_args.kwargs["existing_fork"] == "team/fork"


def test_missing_live_configuration_fails_without_exposing_values(monkeypatch):
    monkeypatch.setattr("ci_agent.cli.load_dotenv", lambda: None)
    for name in ("CRUSOE_API_KEY", "CRUSOE_MODEL", "CRUSOE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    result = CliRunner().invoke(main, ["smoke", "--live"])
    assert result.exit_code != 0
    assert "Missing configuration: CRUSOE_API_KEY, CRUSOE_MODEL" in result.output


def test_runner_smoke_writes_local_backend_receipt(tmp_path):
    result = CliRunner().invoke(main, ["runner-smoke", "--output", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "not GitHub Actions" in result.output
    receipt = (tmp_path / "runner-smoke.json").read_text(encoding="utf-8")
    assert '"status": "passed"' in receipt
    assert '"backend": "local child process"' in receipt


def test_inference_smoke_saves_response_without_credentials(monkeypatch, tmp_path):
    class FakeClient:
        api_key = "never-save-this-key"
        model = "example/model"
        base_url = "https://api.inference.crusoecloud.com/v1"

        def complete(self, **kwargs):
            assert kwargs["max_tokens"] == 256
            return "READY"

    monkeypatch.setattr("ci_agent.cli.load_dotenv", lambda: None)
    monkeypatch.setattr("ci_agent.cli.CrusoeInference.from_env", lambda: FakeClient())
    result = CliRunner().invoke(main, ["inference-smoke", "--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    receipt = (tmp_path / "inference-smoke.json").read_text(encoding="utf-8")
    assert '"response": "READY"' in receipt
    assert "never-save-this-key" not in receipt


def test_contract_generation_surfaces_unselected_interval_calculation(tmp_path):
    import json
    from pathlib import Path

    request = json.loads(Path("config/contract-request.example.json").read_text(encoding="utf-8"))
    request["limits"]["uncertainty_method"] = None
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "contract-generate",
            str(request_path),
            "--output",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "What uncertainty method" in result.output
    saved = (tmp_path / "generation-result.json").read_text(encoding="utf-8")
    assert '"status": "needs_human"' in saved
    assert not (tmp_path / "success-contract.json").exists()
