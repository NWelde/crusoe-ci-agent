from click.testing import CliRunner

from ci_agent.cli import main


def test_local_smoke_requires_no_credentials():
    result = CliRunner().invoke(main, ["smoke"])
    assert result.exit_code == 0
    assert "Local SQLite smoke check passed" in result.output


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
