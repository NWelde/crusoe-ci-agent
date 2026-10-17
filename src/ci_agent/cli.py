"""Operator entry point for local diagnostics and simulated experiment walkthroughs."""
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import click
from dotenv import load_dotenv
from pydantic import ValidationError

from ci_agent.contracts import (
    ContractRequest,
    generate_contract,
    save_contract,
)
from ci_agent.experiments.demo_loop import DemoRunConfig, run_demo
from ci_agent.github.runs import GitHubAPIError, GitHubClient, sample_runs
from ci_agent.inference import CrusoeInference, InferenceError


def _echo_console_safe(message: str) -> None:
    """Print model-authored text on Windows consoles with legacy encodings."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    click.echo(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))


@click.group()
def main():
    """CI improvement agent: setup and diagnostics."""


@main.command()
@click.option("--live", is_flag=True, help="Call Crusoe and run a local process smoke check.")
def smoke(live):
    """Check local runtime; optionally run live inference and local runner checks."""
    if live:
        load_dotenv()
        _run_inference_smoke(Path("artifacts/bro-6-smoke"))
        _run_runner_smoke(Path("artifacts/bro-6-smoke"))
    with sqlite3.connect(":memory:") as connection:
        connection.execute("SELECT 1").fetchone()
    click.echo("Local SQLite smoke check passed.")


def _write_smoke_artifact(output: Path, name: str, content: dict[str, object]) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / name
    path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _run_inference_smoke(output: Path) -> dict[str, object]:
    """Make one real, low-impact inference request and save a redacted receipt."""
    try:
        client = CrusoeInference.from_env()
        response = client.complete(
            system_prompt="You are a connectivity checker. Return exactly READY and nothing else.",
            user_prompt="Reply with the single word READY.",
            max_tokens=256,
        )
    except InferenceError as exc:
        raise click.ClickException(str(exc)) from exc
    safe_response = response.replace(client.api_key, "[REDACTED]")
    parsed = urlparse(client.base_url)
    receipt = {
        "check": "crusoe_managed_inference",
        "status": "passed",
        "captured_at": datetime.now(UTC).isoformat(),
        "model": client.model,
        "endpoint": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        "response": safe_response,
        "response_sha256": hashlib.sha256(safe_response.encode("utf-8")).hexdigest(),
        "evidence_note": "Actual response received; API key and request headers are not recorded.",
    }
    path = _write_smoke_artifact(output, "inference-smoke.json", receipt)
    click.echo(f"Crusoe inference smoke passed (model: {client.model}). Evidence: {path}")
    return receipt


def _run_runner_smoke(output: Path) -> dict[str, object]:
    """Verify this host can start a clean Python child process and capture output."""
    try:
        with tempfile.TemporaryDirectory(prefix="ci-agent-runner-smoke-") as temp_dir:
            completed = subprocess.run(
                [sys.executable, "-c", "print('RUNNER_OK')"], cwd=temp_dir, check=True,
                capture_output=True, text=True, timeout=15,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise click.ClickException(f"Local runner smoke failed: {type(exc).__name__}.") from None
    if completed.stdout.strip() != "RUNNER_OK":
        raise click.ClickException("Local runner smoke returned unexpected output.")
    receipt = {
        "check": "runner_process",
        "status": "passed",
        "captured_at": datetime.now(UTC).isoformat(),
        "backend": "local child process",
        "runtime": f"Python {platform.python_version()}",
        "output": completed.stdout.strip(),
        "evidence_note": "This verifies the local execution host, not a GitHub Actions runner.",
    }
    path = _write_smoke_artifact(output, "runner-smoke.json", receipt)
    click.echo(f"Local runner process smoke passed (not GitHub Actions). Evidence: {path}")
    return receipt


@main.command("inference-smoke")
@click.option("--output", type=click.Path(path_type=Path), default=Path("artifacts/bro-6-smoke"),
              show_default=True, help="Directory for the redacted inference receipt.")
def inference_smoke(output: Path) -> None:
    """Send a minimal live request to the configured Crusoe model."""
    load_dotenv()
    _run_inference_smoke(output)


@main.command("runner-smoke")
@click.option("--output", type=click.Path(path_type=Path), default=Path("artifacts/bro-6-smoke"),
              show_default=True, help="Directory for the local runner receipt.")
def runner_smoke(output: Path) -> None:
    """Check that the current host can launch a clean Python process."""
    _run_runner_smoke(output)


@main.command("contract-generate")
@click.argument("request_file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--output", type=click.Path(path_type=Path), default=Path("artifacts/contracts"),
              show_default=True, help="Directory for the reviewed contract or human question.")
@click.option("--uncertainty-method", help="Explicitly selected method for judging measurement uncertainty.")
def contract_generate(request_file: Path, output: Path, uncertainty_method: str | None) -> None:
    """Generate and independently review a locked experiment success contract."""
    try:
        request = ContractRequest.model_validate_json(request_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(f"Invalid contract request: {exc}") from exc
    if uncertainty_method:
        request = request.model_copy(update={
            "limits": request.limits.model_copy(update={"uncertainty_method": uncertainty_method})
        })
        # model_copy skips validation, so revalidate all locked settings.
        request = ContractRequest.model_validate(request.model_dump(mode="python"))
    if request.limits.uncertainty_method:
        load_dotenv()
        try:
            client = CrusoeInference.from_env()
        except InferenceError as exc:
            raise click.ClickException(str(exc)) from exc
    else:
        client = None

    try:
        result = generate_contract(request.goal, request.context, request.limits, client)
    except InferenceError as exc:
        raise click.ClickException(str(exc)) from exc
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "generation-result.json"
    result_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if result.status == "ready":
        assert result.sealed_contract is not None
        contract_path = output / "success-contract.json"
        save_contract(contract_path, result.sealed_contract)
        click.echo(f"Reviewed contract saved: {contract_path}")
        click.echo(f"Contract ID: {result.sealed_contract.contract.id}")
        click.echo(f"Contract fingerprint: {result.sealed_contract.contract_fingerprint}")
    elif result.status == "needs_human":
        click.echo(f"Human input needed: {result.human_question}")
        click.echo(f"Question saved: {result_path}")
    else:
        click.echo("Contract rejected:")
        for reason in result.reasons:
            _echo_console_safe(f"- {reason}")
        if result.human_question:
            _echo_console_safe(f"Human question: {result.human_question}")
        click.echo(f"Review result saved: {result_path}")


@main.command("demo-loop")
@click.option("--output", type=click.Path(path_type=Path), default=Path("artifacts/bro-31-demo"),
              show_default=True, help="Directory for the simulated timeline and reports.")
@click.option("--config", "config_path", type=click.Path(path_type=Path, exists=True, dir_okay=False),
              help="Optional JSON settings for required checks, sample count, and reporting threshold.")
@click.option("--consecutive", is_flag=True,
              help="Use the later-improvement rule (any evidence-backed reduction).")
@click.option("--live", is_flag=True,
              help="Request live execution; currently fails until real adapters are supplied.")
@click.option("--fail-check", is_flag=True,
              help="Demonstrate the required-check failure and stop path.")
def demo_loop(output: Path, config_path: Path | None, consecutive: bool, live: bool,
              fail_check: bool) -> None:
    """Run the local end-to-end loop with clearly labeled simulated adapters."""
    if live:
        raise click.ClickException(
            "Live adapters are not implemented. No simulated adapter was used; "
            "select local demo mode by omitting --live."
        )
    try:
        config = (
            DemoRunConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
            if config_path
            else None
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Invalid demo config: {exc}") from exc
    report = run_demo(output, config=config, consecutive=consecutive, fail_check=fail_check)
    click.echo(report["label"])
    click.echo(f"Status: {report['status']}")
    if report["verdict"]:
        verdict = report["verdict"]
        click.echo(f"Verdict: {verdict['outcome']}")
        if "reduction_percent" in verdict:
            click.echo(f"Runner-minute reduction: {verdict['reduction_percent']}%")
            click.echo(f"Required checks passed: {verdict['required_checks_enabled_and_passed']}")
    click.echo(f"Timeline: {output / 'events.jsonl'}")
    click.echo(f"Agent trace: {output / 'agent-trace.md'}")
    click.echo(f"Report: {output / 'report.md'}")


@main.command("sample-github-runs")
@click.option("--repository", default="madeintandem/jsonb_accessor", show_default=True)
@click.option("--workflow-id", default="", help="Optional exact GitHub workflow ID to filter.")
@click.option("--limit", type=click.IntRange(1, 100), default=30, show_default=True)
@click.option("--output", type=click.Path(path_type=Path), default=Path("artifacts/github-run-sample.json"), show_default=True)
def sample_github_runs(repository: str, workflow_id: str, limit: int, output: Path) -> None:
    """Read recent GitHub Actions runs and required-job timings; no writes or dispatches."""
    if repository.count("/") != 1 or any(not part.strip() for part in repository.split("/")):
        raise click.ClickException("Repository must be OWNER/REPO.")
    owner, repo = repository.split("/", 1)
    try:
        client = GitHubClient.from_env()
        _, _, report = sample_runs(
            client, owner, repo, limit=limit, workflow_id=workflow_id or None,
            required_checks=("lint", "tests"),
            required_job_patterns={"tests": ("Active Record ",)},
        )
    except GitHubAPIError as exc:
        raise click.ClickException(str(exc)) from None
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    click.echo(f"Sampled {report['runs_returned']} runs from {repository} (read-only).")
    click.echo(f"Evidence: {output}")
