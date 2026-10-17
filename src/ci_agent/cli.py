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
from ci_agent.experiments.live_loop import run_live
from ci_agent.github.fork_experiment import dispatch_matched_runs, prepare_fork_experiment
from ci_agent.github.runs import GitHubAPIError, GitHubClient, sample_runs
from ci_agent.inference import CrusoeInference, InferenceError


def _echo_console_safe(message: str) -> None:
    """Print model-authored text on Windows consoles with legacy encodings."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    click.echo(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))


@click.group()
def main():
    """CI improvement agent: setup and diagnostics."""


@main.command("live-e2e")
@click.option("--repository", default="madeintandem/jsonb_accessor", show_default=True)
@click.option("--fork-repository", required=True)
@click.option("--output", required=True, type=click.Path(path_type=Path))
@click.option(
    "--template",
    default=Path("config/contract-request.example.json"),
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option("--common-source-files", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--resume", is_flag=True)
@click.option(
    "--mode", type=click.Choice(["shadow", "research"]), default="shadow", show_default=True
)
@click.option("--publish-draft", is_flag=True)
@click.option("--confirm-live-runs", is_flag=True)
def live_e2e(
    repository,
    fork_repository,
    output,
    template,
    common_source_files,
    resume,
    mode,
    publish_draft,
    confirm_live_runs,
):
    """Generate a reviewed proposal and compare one pair by default for the demo."""
    if not confirm_live_runs:
        raise click.UsageError(
            "Pass --confirm-live-runs to create branches and consume Actions minutes."
        )
    from ci_agent.experiments.live_setup import prepare_e2e

    try:
        source = prepare_e2e(
            repository=repository, output=output / "setup", template=template, resume=resume
        )
        execution = output / "execution"
        result = run_live(
            GitHubClient.from_git_credential(),
            repository=repository,
            workflow_path=source["workflow_path"],
            source_revision=source["sha"],
            candidate_path=output / "setup" / "proposal" / "candidate.yml",
            contract_path=output / "setup" / "contract" / "success-contract.json",
            output=execution,
            run_key=output.name,
            existing_fork=fork_repository,
            common_source_files=(
                json.loads(common_source_files.read_text(encoding="utf-8"))
                if common_source_files
                else None
            ),
            optimization="service_readiness",
            resume=resume and execution.exists(),
            evaluation_mode=mode,
        )
        if publish_draft:
            result = _publish_live_result(result, execution)
    except (
        GitHubAPIError,
        InferenceError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(
        f"Live E2E completed. Outcome: {result['outcome']}. Evidence: {execution / 'report.md'}"
    )


@main.command("live-loop")
@click.option("--repository", default="madeintandem/jsonb_accessor", show_default=True)
@click.option("--workflow-path", default=".github/workflows/ci.yml", show_default=True)
@click.option(
    "--candidate-workflow",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option(
    "--contract",
    "contract_path",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option("--output", required=True, type=click.Path(path_type=Path))
@click.option("--run-key", required=True)
@click.option("--fork-repository", help="Use an existing fork owned by the authenticated account.")
@click.option(
    "--common-source-files",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="JSON path-to-content repairs applied to the shared source before both variants.",
)
@click.option("--source-revision", help="Pin the inspected upstream commit.")
@click.option(
    "--optimization",
    type=click.Choice(["parallelism", "service_readiness"]),
    default="parallelism",
    show_default=True,
)
@click.option("--resume", is_flag=True, help="Reconcile saved run IDs without redispatching them.")
@click.option("--prepared-fork", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--baseline-run-id", type=int, help="Reuse an exact baseline qualification run.")
@click.option(
    "--mode", type=click.Choice(["shadow", "research"]), default="shadow", show_default=True
)
@click.option("--publish-draft", is_flag=True)
@click.option(
    "--confirm-live-runs", is_flag=True, help="Create an isolated fork and consume Actions minutes."
)
def live_loop(
    repository,
    workflow_path,
    candidate_workflow,
    contract_path,
    output,
    run_key,
    fork_repository,
    common_source_files,
    source_revision,
    optimization,
    resume,
    prepared_fork,
    baseline_run_id,
    mode,
    publish_draft,
    confirm_live_runs,
):
    """Compare a reviewed workflow change using the selected measurement policy."""
    if not confirm_live_runs:
        raise click.UsageError(
            "Pass --confirm-live-runs to create a fork and consume Actions minutes."
        )
    try:
        result = run_live(
            GitHubClient.from_git_credential(),
            repository=repository,
            workflow_path=workflow_path,
            candidate_path=candidate_workflow,
            contract_path=contract_path,
            output=output,
            run_key=run_key,
            existing_fork=fork_repository,
            common_source_files=(
                json.loads(common_source_files.read_text(encoding="utf-8"))
                if common_source_files
                else None
            ),
            source_revision=source_revision,
            optimization=optimization,
            resume=resume,
            prepared_fork=(
                json.loads(prepared_fork.read_text(encoding="utf-8")) if prepared_fork else None
            ),
            baseline_run_id=baseline_run_id,
            evaluation_mode=mode,
        )
        if publish_draft:
            result = _publish_live_result(result, output)
    except (GitHubAPIError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(f"Outcome: {result['outcome']}. Evidence: {output / 'report.json'}")


def _publish_live_result(result, output):
    if result.get("evaluation_mode") == "shadow":
        from ci_agent.reporting.shadow_pr import publish_shadow_draft

        return publish_shadow_draft(GitHubClient.from_git_credential(), result, output)
    if result["outcome"] == "win":
        from ci_agent.reporting.live_pr import publish_verified_draft

        return publish_verified_draft(GitHubClient.from_git_credential(), result, output)
    return result


@main.command("shadow-report")
@click.option(
    "--evidence", required=True, type=click.Path(path_type=Path, exists=True, dir_okay=False)
)
@click.option("--output", required=True, type=click.Path(path_type=Path))
@click.option("--publish-draft", is_flag=True)
def shadow_report(evidence, output, publish_draft):
    """Reuse the earliest real pair for a demo, retaining all later observations."""
    from ci_agent.experiments.shadow_report import create_shadow_report

    try:
        result = create_shadow_report(evidence, output)
        if publish_draft:
            result = _publish_live_result(result, output)
    except (GitHubAPIError, OSError, ValueError, KeyError, TypeError) as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(f"Shadow demo: {result['outcome']}. Report: {output / 'report.md'}")
    if result.get("draft_pr_url"):
        click.echo(f"Draft PR: {result['draft_pr_url']}")


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
                [sys.executable, "-c", "print('RUNNER_OK')"],
                cwd=temp_dir,
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
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
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("artifacts/bro-6-smoke"),
    show_default=True,
    help="Directory for the redacted inference receipt.",
)
def inference_smoke(output: Path) -> None:
    """Send a minimal live request to the configured Crusoe model."""
    load_dotenv()
    _run_inference_smoke(output)


@main.command("runner-smoke")
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("artifacts/bro-6-smoke"),
    show_default=True,
    help="Directory for the local runner receipt.",
)
def runner_smoke(output: Path) -> None:
    """Check that the current host can launch a clean Python process."""
    _run_runner_smoke(output)


@main.command("contract-generate")
@click.argument("request_file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("artifacts/contracts"),
    show_default=True,
    help="Directory for the reviewed contract or human question.",
)
@click.option(
    "--uncertainty-method", help="Explicitly selected method for judging measurement uncertainty."
)
def contract_generate(request_file: Path, output: Path, uncertainty_method: str | None) -> None:
    """Generate and independently review a locked experiment success contract."""
    try:
        request = ContractRequest.model_validate_json(request_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(f"Invalid contract request: {exc}") from exc
    if uncertainty_method:
        request = request.model_copy(
            update={
                "limits": request.limits.model_copy(
                    update={"uncertainty_method": uncertainty_method}
                )
            }
        )
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
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("artifacts/bro-31-demo"),
    show_default=True,
    help="Directory for the simulated timeline and reports.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="Optional JSON settings for required checks, sample count, and reporting threshold.",
)
@click.option(
    "--consecutive",
    is_flag=True,
    help="Use the later-improvement rule (any evidence-backed reduction).",
)
@click.option(
    "--live",
    is_flag=True,
    help="Request live execution; currently fails until real adapters are supplied.",
)
@click.option(
    "--fail-check", is_flag=True, help="Demonstrate the required-check failure and stop path."
)
def demo_loop(
    output: Path, config_path: Path | None, consecutive: bool, live: bool, fail_check: bool
) -> None:
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
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("artifacts/github-run-sample.json"),
    show_default=True,
)
def sample_github_runs(repository: str, workflow_id: str, limit: int, output: Path) -> None:
    """Read recent GitHub Actions runs and required-job timings; no writes or dispatches."""
    if repository.count("/") != 1 or any(not part.strip() for part in repository.split("/")):
        raise click.ClickException("Repository must be OWNER/REPO.")
    owner, repo = repository.split("/", 1)
    try:
        client = GitHubClient.from_env()
        _, _, report = sample_runs(
            client,
            owner,
            repo,
            limit=limit,
            workflow_id=workflow_id or None,
            required_checks=("lint", "tests"),
            required_job_patterns={"tests": ("Active Record ",)},
        )
    except GitHubAPIError as exc:
        raise click.ClickException(str(exc)) from None
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    click.echo(f"Sampled {report['runs_returned']} runs from {repository} (read-only).")
    click.echo(f"Evidence: {output}")


@main.command("fork-experiment")
@click.option("--upstream", required=True, help="Source repository as OWNER/REPO.")
@click.option("--workflow-path", required=True, help="Workflow path under .github/workflows/.")
@click.option(
    "--candidate-workflow",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    required=True,
    help="Reviewed candidate workflow YAML file.",
)
@click.option(
    "--baseline-workflow",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="Optional explicit baseline YAML; otherwise read from upstream.",
)
@click.option("--run-key", required=True, help="Experiment identifier for fork/branch names.")
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("artifacts/fork-experiment"),
    show_default=True,
)
@click.option(
    "--confirm-live-runs",
    is_flag=True,
    help="Required: creates a fork and consumes GitHub Actions minutes.",
)
def fork_experiment(
    upstream: str,
    workflow_path: str,
    candidate_workflow: Path,
    baseline_workflow: Path | None,
    run_key: str,
    output: Path,
    confirm_live_runs: bool,
) -> None:
    """Create a retained isolated fork and collect matched Actions runs."""
    if not confirm_live_runs:
        raise click.UsageError(
            "Pass --confirm-live-runs to create a fork and consume Actions minutes."
        )
    try:
        client = GitHubClient.from_git_credential()
        candidate = candidate_workflow.read_text(encoding="utf-8")
        baseline = baseline_workflow.read_text(encoding="utf-8") if baseline_workflow else None
        fork = prepare_fork_experiment(
            client,
            upstream,
            workflow_path,
            candidate,
            run_key=run_key,
            baseline_workflow=baseline,
        )
        click.echo(f"Prepared {fork.repository} from {fork.base_sha}; dispatching matched runs.")
        result = dispatch_matched_runs(client, fork)
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / f"{run_key}-runs.json"
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        click.echo(f"Evidence: {report_path}")
        click.echo(f"Fork retained: https://github.com/{fork.repository}")
    except (GitHubAPIError, TimeoutError, OSError, ValueError, KeyError) as exc:
        raise click.ClickException(str(exc)) from None
