import json

import pytest
import yaml
from click.testing import CliRunner

from ci_agent.cli import main
from ci_agent.strategies import REGISTRY, discover, parse, validate_strategy

FIXTURES = {
    "parallelism": """name: fixture-dag
on: push
jobs:
  lint:
    runs-on: ubuntu-24.04
    steps:
      - run: echo lint
  tests:
    needs: lint
    if: always()
    runs-on: ubuntu-24.04
    steps:
      - run: echo tests
""",
    "checkout_reduction": """name: fixture-checkout
on: push
jobs:
  tests:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - run: echo tests
""",
    "setup_removal": """name: fixture-setup
on: push
jobs:
  tests:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      - run: echo tests
""",
    "superseded_cancellation": """name: fixture-cancellation
on: pull_request
jobs:
  tests:
    runs-on: ubuntu-24.04
    steps:
      - run: echo tests
""",
    "service_readiness": """name: fixture-service
on: push
jobs:
  tests:
    runs-on: ubuntu-24.04
    services:
      db:
        image: postgres:17
        options: --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
    steps:
      - run: echo tests
""",
}


@pytest.mark.parametrize("strategy", REGISTRY)
def test_discovery_and_exact_validation(strategy):
    baseline = FIXTURES[strategy]
    proposals, rejected = discover(baseline)
    selected = next(p for p in proposals if p["optimization"] == strategy)
    assert strategy not in rejected
    validate_strategy(strategy, baseline, selected["candidate_workflow"])
    changed = parse(selected["candidate_workflow"])
    changed["jobs"]["tests"]["steps"].append({"run": "echo omitted-check"})
    with pytest.raises(ValueError):
        validate_strategy(strategy, baseline, yaml.safe_dump(changed))
    with pytest.raises(ValueError):
        validate_strategy(strategy, baseline, baseline)


@pytest.mark.parametrize(
    ("strategy", "old", "new"),
    [
        ("parallelism", "    if: always()\n", ""),
        ("parallelism", "echo tests", "echo ${{ needs.lint.outputs.result }}"),
        ("parallelism", "echo lint", "upload-artifact"),
        ("checkout_reduction", "echo tests", "python tests.py"),
        ("checkout_reduction", "echo tests", "echo $(cat secret)"),
        ("setup_removal", "echo tests", "npm test"),
        ("setup_removal", "node-version: '22'", "node-version: '22'\n          cache: npm"),
        ("superseded_cancellation", "on: pull_request", "on: [push, pull_request]"),
        ("superseded_cancellation", "echo tests", "deploy"),
        ("service_readiness", "--health-timeout 5s ", ""),
    ],
)
def test_rejects_missing_soundness_evidence(strategy, old, new):
    assert REGISTRY[strategy].propose(FIXTURES[strategy].replace(old, new)) is None


def test_no_eligible_change_and_no_silent_cache_fallback(tmp_path):
    path = tmp_path / "workflow.yml"
    path.write_text(
        "jobs:\n  tests:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
    )
    output = tmp_path / "discovery"
    result = CliRunner().invoke(
        main, ["strategies", "--workflow", str(path), "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    audit = json.loads((output / "discovery.json").read_text())
    assert audit["eligible"] == []
    assert set(audit["rejected"]) == set(REGISTRY)
    assert "sharding_balancing" in audit["recommendation_only"]


def test_dump_preserves_github_on_key():
    proposal = REGISTRY["superseded_cancellation"].propose(FIXTURES["superseded_cancellation"])
    assert "'on': pull_request" in proposal["candidate_workflow"]


def test_unknown_strategy_never_defaults_to_parallelism_or_cache():
    with pytest.raises(ValueError, match="Unsupported"):
        validate_strategy("caching", FIXTURES["parallelism"], FIXTURES["parallelism"])


@pytest.mark.parametrize(
    "strategy", ["parallelism", "checkout_reduction", "setup_removal", "superseded_cancellation"]
)
def test_shell_startup_hooks_cannot_invalidate_literal_command_proof(strategy):
    for prefix in (
        "env:\n  BASH_ENV: dangerous.sh\n",
        "defaults:\n  run:\n    shell: custom {0}\n",
    ):
        assert REGISTRY[strategy].propose(prefix + FIXTURES[strategy]) is None


def test_readiness_rejects_duplicate_or_embedded_health_flags():
    baseline = FIXTURES["service_readiness"]
    assert (
        REGISTRY["service_readiness"].propose(
            baseline.replace("--health-interval 10s", "--health-interval 10s --health-interval 30s")
        )
        is None
    )
    assert (
        REGISTRY["service_readiness"].propose(
            baseline.replace("pg_isready", "'echo --health-interval 10s'")
        )
        is None
    )
