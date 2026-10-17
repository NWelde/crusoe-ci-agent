from click.testing import CliRunner

from ci_agent.cli import main


def test_local_smoke_requires_no_credentials():
    result = CliRunner().invoke(main, ["smoke"])
    assert result.exit_code == 0
    assert "Local smoke check passed" in result.output


def test_missing_live_configuration_fails_without_exposing_values(monkeypatch):
    monkeypatch.setattr("ci_agent.cli.load_dotenv", lambda: None)
    for name in ("GITHUB_TOKEN", "CRUSOE_API_KEY", "CRUSOE_BASE_URL", "CRUSOE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    result = CliRunner().invoke(main, ["smoke", "--live"])
    assert result.exit_code != 0
    assert "Missing configuration: GITHUB_TOKEN" in result.output
