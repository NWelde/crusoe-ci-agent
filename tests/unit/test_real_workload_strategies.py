"""Eligibility and rejection on real build/test commands, not logging stand-ins."""

import json

import pytest
import yaml

from ci_agent.strategies import REGISTRY, discover, parse, validate_strategy
from ci_agent.workflows.usage import command_usage, job_usage

SOURCES = {
    "complete": True,
    "revision": "fixture",
    "files": {
        "package.json": json.dumps(
            {"scripts": {"test": "vitest run", "lint": "eslint .", "build": "tsc --noEmit"}}
        ),
        "pyproject.toml": '[project]\nname="example"\nversion="1.0"\n',
        "tests/test_total.py": "def test_total():\n    assert sum([1, 2, 3]) == 6\n",
        "scripts/test.sh": "#!/bin/sh\nset -eu\npython -m pytest -q\n",
    },
}


def workflow(steps, **job_options):
    return yaml.safe_dump(
        {
            "name": "CI",
            "on": ["push", "pull_request"],
            "jobs": {"tests": {"runs-on": "ubuntu-latest", **job_options, "steps": steps}},
        },
        sort_keys=False,
    )


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest -q",
        "pytest --cov=src",
        "npm ci && npm test",
        "npm run lint && npm run build",
        "go test ./...",
        "cargo test --all-features",
        "bash scripts/test.sh",
    ],
)
def test_cancellation_for_actual_build_and_test_workloads(command):
    baseline = workflow([{"uses": "actions/checkout@v4"}, {"run": command}])
    proposal = REGISTRY["superseded_cancellation"].propose(baseline, SOURCES)
    assert proposal is not None
    candidate = parse(proposal["candidate_workflow"])
    assert candidate["jobs"] == parse(baseline)["jobs"]
    assert "github.ref_type == 'branch'" in candidate["concurrency"]["cancel-in-progress"]
    assert "github.event_name == 'pull_request'" in candidate["concurrency"]["cancel-in-progress"]
    assert "github.run_id" in candidate["concurrency"]["group"]
    validate_strategy("superseded_cancellation", baseline, proposal["candidate_workflow"], SOURCES)


@pytest.mark.parametrize("command", ["pytest -q", "npm test", "go test ./...", "cargo test"])
def test_parallelism_preserves_real_test_commands_and_failure_independent_condition(command):
    job = {"runs-on": "ubuntu-latest", "steps": [{"uses": "actions/checkout@v4"}, {"run": command}]}
    raw = yaml.safe_dump(
        {"on": "push", "jobs": {"lint": job, "tests": job | {"needs": "lint", "if": "always()"}}}
    )
    proposal = REGISTRY["parallelism"].propose(raw, SOURCES)
    assert proposal is not None
    expected = parse(raw)
    del expected["jobs"]["tests"]["needs"]
    assert parse(proposal["candidate_workflow"]) == expected


@pytest.mark.parametrize(
    "command", ["pytest -q", "npm test", "go test ./...", "./arbitrary-build-script"]
)
def test_duplicate_checkout_can_be_removed_before_arbitrary_real_workload(command):
    step = {"uses": "actions/checkout@v4", "with": {"fetch-depth": 1}}
    baseline = workflow([step, step.copy(), {"run": command}])
    proposal = REGISTRY["checkout_reduction"].propose(baseline, SOURCES)
    assert proposal is not None
    assert parse(proposal["candidate_workflow"])["jobs"]["tests"]["steps"] == [
        step,
        {"run": command},
    ]


@pytest.mark.parametrize("command", ["pytest -q", "npm test", "go test ./..."])
def test_full_history_reduction_keeps_working_tree_and_all_checks(command):
    baseline = workflow(
        [{"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}}, {"run": command}]
    )
    proposal = REGISTRY["checkout_reduction"].propose(baseline, SOURCES)
    assert proposal is not None
    expected = parse(baseline)
    expected["jobs"]["tests"]["steps"][0]["with"]["fetch-depth"] = 1
    assert parse(proposal["candidate_workflow"]) == expected
    assert REGISTRY["checkout_reduction"].propose(baseline, SOURCES | {"complete": False}) is None


@pytest.mark.parametrize("command", ["npm ci && npm test", "pytest -q", "./arbitrary-build-script"])
def test_overwritten_setup_is_removed_without_restricting_remaining_workload(command):
    first = {"uses": "actions/setup-node@v4", "with": {"node-version": "20"}}
    final = {"uses": "actions/setup-node@v4", "with": {"node-version": "22"}}
    if command.startswith("pytest"):
        first = {"uses": "actions/setup-python@v5", "with": {"python-version": "3.11"}}
        final = {"uses": "actions/setup-python@v5", "with": {"python-version": "3.12"}}
    baseline = workflow([first, {"uses": "actions/checkout@v4"}, final, {"run": command}])
    proposal = REGISTRY["setup_removal"].propose(baseline, SOURCES)
    assert proposal is not None
    assert parse(proposal["candidate_workflow"])["jobs"]["tests"]["steps"] == [
        {"uses": "actions/checkout@v4"},
        final,
        {"run": command},
    ]


def test_unused_node_setup_is_removed_from_python_tests_but_python_setup_is_retained():
    node = {"uses": "actions/setup-node@v4", "with": {"node-version": "22"}}
    python = {"uses": "actions/setup-python@v5", "with": {"python-version": "3.12"}}
    baseline = workflow(
        [{"uses": "actions/checkout@v4"}, node, python, {"run": "python -m pytest -q"}]
    )
    proposal = REGISTRY["setup_removal"].propose(baseline, SOURCES)
    assert proposal is not None
    assert node not in parse(proposal["candidate_workflow"])["jobs"]["tests"]["steps"]
    assert python in parse(proposal["candidate_workflow"])["jobs"]["tests"]["steps"]


@pytest.mark.parametrize(
    "mutation", ["output", "artifact", "success_gate", "self_hosted", "secret"]
)
def test_real_dag_dependencies_are_not_discarded(mutation):
    job = {"runs-on": "ubuntu-latest", "steps": [{"run": "pytest -q"}]}
    before = {
        "on": "push",
        "jobs": {"lint": job, "tests": job | {"needs": "lint", "if": "always()"}},
    }
    if mutation == "output":
        before["jobs"]["tests"]["steps"] = [{"run": "echo ${{ needs.lint.outputs.result }}"}]
    elif mutation == "artifact":
        before["jobs"]["tests"]["steps"] = [
            {"uses": "actions/download-artifact@v4"},
            {"run": "pytest -q"},
        ]
    elif mutation == "success_gate":
        before["jobs"]["tests"].pop("if")
    elif mutation == "self_hosted":
        before["jobs"]["tests"]["runs-on"] = ["self-hosted", "linux"]
    else:
        before["env"] = {"DATABASE_URL": "${{ secrets.PRODUCTION_DATABASE }}"}
    assert REGISTRY["parallelism"].propose(yaml.safe_dump(before), SOURCES) is None


@pytest.mark.parametrize(
    "command", ["git describe --tags", "npm run build", "bash scripts/test.sh"]
)
def test_transitive_history_usage_prevents_shallow_clone(command):
    files = SOURCES["files"] | {
        "package.json": json.dumps({"scripts": {"build": "git describe --tags"}}),
        "scripts/test.sh": "git log -1\npython -m pytest -q\n",
    }
    baseline = workflow(
        [{"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}}, {"run": command}]
    )
    assert REGISTRY["checkout_reduction"].propose(baseline, SOURCES | {"files": files}) is None


@pytest.mark.parametrize(
    "script", ["npm publish", "curl https://example.com/deploy", "terraform apply", "npm run test"]
)
def test_package_lifecycle_deployment_and_recursive_scripts_are_rejected(script):
    sources = SOURCES | {"files": {"package.json": json.dumps({"scripts": {"test": script}})}}
    baseline = workflow([{"run": "npm test"}])
    assert REGISTRY["superseded_cancellation"].propose(baseline, sources) is None


def test_runtime_use_between_setup_steps_and_cache_outputs_are_preserved():
    first = {"uses": "actions/setup-node@v4", "with": {"node-version": "20"}}
    final = {"uses": "actions/setup-node@v4", "with": {"node-version": "22"}}
    baseline = workflow([first, {"run": "npm test"}, final, {"run": "npm test"}])
    assert REGISTRY["setup_removal"].propose(baseline, SOURCES) is None
    first["with"]["cache"] = "npm"
    baseline = workflow([first, final, {"run": "npm test"}])
    assert REGISTRY["setup_removal"].propose(baseline, SOURCES) is None


def test_shell_and_composite_action_closure_and_working_directories():
    files = SOURCES["files"] | {
        "frontend/package.json": SOURCES["files"]["package.json"],
        ".github/actions/test/action.yml": "runs:\n  using: composite\n  steps:\n    - run: python -m pytest -q\n      shell: bash\n",
    }
    assert not command_usage("cd frontend && npm test", files).unknown
    usage = job_usage({"steps": [{"uses": "./.github/actions/test"}]}, files)
    assert not usage.unknown
    assert "python" in usage.runtimes
    assert usage.workspace


def test_missing_script_evidence_disables_only_the_affected_strategy():
    baseline = workflow(
        [{"uses": "actions/checkout@v4"}, {"uses": "actions/checkout@v4"}, {"run": "npm test"}]
    )
    proposals, rejected = discover(baseline)
    assert "checkout_reduction" in {p["optimization"] for p in proposals}
    assert "superseded_cancellation" in rejected


def test_failure_status_observers_are_real_dependency_consumers():
    job = {"runs-on": "ubuntu-latest", "steps": [{"run": "pytest -q"}]}
    dependent = job | {
        "needs": "lint",
        "if": "always()",
        "steps": [{"run": "pytest -q", "if": "failure()"}],
    }
    raw = yaml.safe_dump({"on": "push", "jobs": {"lint": job, "tests": dependent}})
    assert REGISTRY["parallelism"].propose(raw, SOURCES) is None


def test_subprocess_git_history_and_scm_libraries_are_detected_in_source():
    raw = workflow(
        [{"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}}, {"run": "pytest -q"}]
    )
    for code in (
        'subprocess.check_output(["git", "describe", "--tags"])',
        "from git import Repo",
        "from setuptools_scm import get_version",
    ):
        evidence = SOURCES | {"files": SOURCES["files"] | {"version.py": code}}
        assert REGISTRY["checkout_reduction"].propose(raw, evidence) is None
