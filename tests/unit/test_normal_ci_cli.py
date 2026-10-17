"""Real Python tests and Node tests through live-e2e; remote transport is a fixture."""

import base64
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from click.testing import CliRunner
from test_strategy_cli_integration import FixtureGitHub, FixtureInference

from ci_agent.cli import main
from ci_agent.strategies import parse
from ci_agent.workflows.source_evidence import git_blob_sha

PROJECT = {
    "tests/test_total.py": "def test_total():\n    assert sum([1, 2, 3]) == 6\n",
    "package.json": json.dumps(
        {
            "name": "ci-workload-fixture",
            "private": True,
            "scripts": {"test": "node --test test-node.cjs"},
        }
    ),
    "test-node.cjs": "const {test} = require('node:test');\nconst assert = require('node:assert/strict');\ntest('sum', () => assert.equal(1 + 2 + 3, 6));\n",
}


class NormalWorkloadGitHub(FixtureGitHub):
    evidence_class = "FIXTURE_GITHUB_TRANSPORT_REAL_PYTEST_AND_NODE_TESTS"

    def __init__(self, baseline):
        super().__init__(baseline)
        self.command_receipts = []
        self.sources = PROJECT | {".github/workflows/ci.yml": baseline}

    def _get(self, path, **kwargs):
        if "/git/trees/" in path:
            return {
                "truncated": False,
                "tree": [
                    {
                        "type": "blob",
                        "path": name,
                        "sha": git_blob_sha(content),
                        "size": len(content.encode()),
                    }
                    for name, content in self.sources.items()
                ],
            }
        return super()._get(path, **kwargs)

    def get_contents(self, owner, name, path, revision):
        if path != ".github/workflows/ci.yml" and path in self.sources:
            content = self.sources[path]
            return {
                "encoding": "base64",
                "content": base64.b64encode(content.encode()).decode(),
                "sha": git_blob_sha(content),
            }
        return super().get_contents(owner, name, path, revision)

    def full_run(self, owner, name, run_id):
        variant = "baseline" if run_id == 1 else "candidate"
        start = datetime.now(UTC)
        jobs = []
        for index, (job_id, job) in enumerate(parse(self.files[variant])["jobs"].items()):
            job_start = datetime.now(UTC)
            with tempfile.TemporaryDirectory(prefix="ci-agent-real-tests-") as directory:
                for path, content in PROJECT.items():
                    destination = Path(directory) / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(content, encoding="utf-8")
                for step in job["steps"]:
                    if "run" not in step:
                        continue  # Actions are simulated; test commands actually execute.
                    command = step["run"]
                    if command.startswith("python "):
                        args = [sys.executable, *command.split()[1:]]
                    elif command == "npm test":
                        npm = shutil.which("npm.cmd") or shutil.which("npm")
                        if npm is None:
                            pytest.skip(
                                "Node/npm unavailable for the Node execution integration fixture"
                            )
                        args = [npm, "test"]
                    else:
                        raise AssertionError(f"Unexpected fixture command: {command}")
                    completed = subprocess.run(
                        args, cwd=directory, capture_output=True, text=True, timeout=30, check=True
                    )
                    self.command_receipts.append(
                        {
                            "variant": variant,
                            "command": command,
                            "stdout": completed.stdout,
                            "returncode": completed.returncode,
                        }
                    )
            jobs.append(
                {
                    "id": run_id * 100 + index,
                    "name": job_id,
                    "conclusion": "success",
                    "started_at": job_start.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                    "labels": ["FIXTURE_LOCAL_PROCESS"],
                }
            )
        return {
            "id": run_id,
            "head_sha": variant,
            "status": "completed",
            "conclusion": "success",
            "created_at": start.isoformat(),
            "run_started_at": start.isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "jobs": jobs,
            "html_url": f"https://example.invalid/real-tests/{run_id}",
            "fixture_actions_and_services_simulated": True,
        }


def real_workflow(strategy, command):
    steps = [{"uses": "actions/checkout@v4"}]
    job = {"runs-on": "ubuntu-latest", "steps": steps}
    jobs = {"tests": job}
    if strategy == "checkout_reduction":
        steps.append({"uses": "actions/checkout@v4"})
    if strategy == "setup_removal":
        steps.extend(
            [
                {"uses": "actions/setup-node@v4", "with": {"node-version": "20"}},
                {"uses": "actions/setup-node@v4", "with": {"node-version": "22"}},
            ]
        )
    if strategy == "parallelism":
        job.update(needs="lint", **{"if": "always()"})
        jobs = {
            "lint": {
                "runs-on": "ubuntu-latest",
                "steps": [{"run": "python -m compileall -q tests"}],
            },
            **jobs,
        }
    steps.append({"run": command})
    return yaml.safe_dump(
        {
            "name": "Normal test workload",
            "on": ["push", "pull_request"],
            "permissions": {"contents": "read"},
            "jobs": jobs,
        },
        sort_keys=False,
    )


@pytest.mark.parametrize(
    ("strategy", "command"),
    [
        ("parallelism", "python -m pytest -q"),
        ("checkout_reduction", "python -m pytest -q"),
        ("setup_removal", "npm test"),
        ("superseded_cancellation", "python -m pytest -q"),
    ],
)
def test_normal_build_test_workloads_through_actual_cli(strategy, command, tmp_path, monkeypatch):
    baseline = real_workflow(strategy, command)
    github = NormalWorkloadGitHub(baseline)
    inference = FixtureInference(strategy)
    monkeypatch.setattr("ci_agent.cli.GitHubClient.from_git_credential", lambda: github)
    monkeypatch.setattr(
        "ci_agent.experiments.live_setup.CrusoeInference.from_env", lambda **_: inference
    )
    monkeypatch.setattr(
        "requests.sessions.Session.request", Mock(side_effect=AssertionError("No live requests"))
    )
    template = json.loads(Path("config/contract-request.example.json").read_text(encoding="utf-8"))
    template["context"]["required_checks"] = [
        {"name": name, "command": job["steps"][-1]["run"], "required": True}
        for name, job in parse(baseline)["jobs"].items()
    ]
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps(template), encoding="utf-8")
    output = tmp_path / "actual-cli"
    args = [
        "live-e2e",
        "--repository",
        "fixture/source",
        "--fork-repository",
        "fixture/fork",
        "--template",
        str(template_path),
        "--output",
        str(output),
        "--confirm-live-runs",
        "--publish-draft",
    ]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    report = json.loads((output / "execution/report.json").read_text(encoding="utf-8"))
    assert report["inputs"]["optimization"] == strategy
    assert report["baseline_passed"] and report["proposed_passed"]
    assert report["sample_pairs"] == 1 and len(github.dispatched) == 2
    assert report["evidence_class"] == github.evidence_class
    assert all(receipt["returncode"] == 0 for receipt in github.command_receipts)
    checks = [r for r in github.command_receipts if r["command"] == command]
    assert len(checks) == 2
    assert all("1 passed" in r["stdout"] or "# pass 1" in r["stdout"] for r in checks)
    assert len(github.drafts) == 1
    # Persist actual child-process outputs separately from synthetic transport receipts.
    (output / "local-test-command-receipts.json").write_text(
        json.dumps(github.command_receipts, indent=2), encoding="utf-8"
    )
    resumed = CliRunner().invoke(main, args + ["--resume"])
    assert resumed.exit_code == 0, resumed.output
    assert len(github.dispatched) == 2


def test_remote_discovery_cli_reads_pinned_source_without_dispatch(tmp_path, monkeypatch):
    github = NormalWorkloadGitHub(real_workflow("superseded_cancellation", "npm test"))
    monkeypatch.setattr("ci_agent.cli.GitHubClient.from_git_credential", lambda: github)
    output = tmp_path / "readonly"
    result = CliRunner().invoke(
        main,
        [
            "strategies",
            "--repository",
            "fixture/source",
            "--workflow-path",
            ".github/workflows/ci.yml",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads((output / "discovery.json").read_text(encoding="utf-8"))
    assert report["source_analysis"]["revision"] == "source"
    assert report["source_analysis"]["complete"]
    assert "superseded_cancellation" in {p["optimization"] for p in report["eligible"]}
    assert github.dispatched == [] and github.drafts == []
