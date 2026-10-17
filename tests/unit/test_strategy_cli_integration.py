"""Labeled fixture transport exercises the real CLI, planner, verifier and loop.

No remote requests or paid runners. Child processes execute literal fixture
checks; GitHub action/service behavior and transport are simulated, never live
optimization evidence. Only network boundaries are replaced.
"""

import base64
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from test_strategies import FIXTURES

from ci_agent.cli import main
from ci_agent.contracts import ContractReview, ContractRules
from ci_agent.experiments.live_proposal import LiveProposal, ProposalReview
from ci_agent.strategies import REGISTRY, parse


class FixtureInference:
    model = "FIXTURE_STRUCTURED_RESPONSES_NOT_LIVE_MODEL"

    def __init__(self, strategy):
        self.strategy = strategy
        self.calls = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs["output_model"].__name__)
        context = json.loads(kwargs["user_prompt"])
        model = kwargs["output_model"]
        if model is ContractRules:
            return ContractRules(
                **(
                    context["locked_limits"]
                    | {
                        "objective": context["goal"]["objective"],
                        "required_checks": context["required_checks"],
                    }
                )
            )
        if model is ContractReview:
            return ContractReview(approved=True, rationale="Fixture contract verifier response")
        if model is LiveProposal:
            selected = next(
                p for p in context["eligible_proposals"] if p["optimization"] == self.strategy
            )
            return LiveProposal(**selected)
        return ProposalReview(approved=True, rationale="Fixture independent verifier response")


class FixtureGitHub:
    evidence_class = "FIXTURE_TRANSPORT_LOCAL_CHECKS_NOT_LIVE_ACTIONS"

    def __init__(self, baseline):
        self.baseline = baseline
        self.files = {"baseline": baseline, "candidate": baseline}
        self.dispatched = []
        self.drafts = []

    def default_branch(self, *args):
        return "main", "source"

    def get_contents(self, owner, name, path, revision):
        raw = self.files.get(revision, self.baseline)
        return {
            "encoding": "base64",
            "content": base64.b64encode(raw.encode()).decode(),
            "sha": "blob",
        }

    def authenticated_user(self):
        return {"login": "fixture"}

    def repository(self, *args):
        return {
            "full_name": "fixture/fork",
            "parent": {"full_name": "fixture/source"},
            "default_branch": "main",
        }

    def create_branch(self, owner, name, branch, sha):
        pass

    def put_file(self, owner, name, path, content, message, branch, **kwargs):
        variant = "candidate" if "candidate" in branch else "baseline"
        self.files[variant] = content
        return {"commit": {"sha": variant}}

    def workflow(self, *args):
        return {"id": "ci"}

    def _get(self, path, **kwargs):
        if "/git/trees/" in path:
            return {"tree": [], "truncated": False}
        if "/compare/" in path:
            return {"status": "ahead", "files": [{"filename": ".github/workflows/ci.yml"}]}
        branch = path.rsplit("/", 1)[1]
        return {"object": {"sha": "candidate" if "candidate" in branch else "baseline"}}

    def dispatch_workflow(self, owner, name, workflow_id, branch):
        self.dispatched.append(branch)

    def wait_for_dispatch_run(self, *args, **kwargs):
        return {"id": len(self.dispatched)}

    def wait_for_run_completion(self, *args, **kwargs):
        pass

    def full_run(self, owner, name, run_id):
        variant = "baseline" if run_id == 1 else "candidate"
        start = datetime.now(UTC)
        jobs = []
        simulated_actions = []
        for index, (job_id, job) in enumerate(parse(self.files[variant])["jobs"].items()):
            job_start = datetime.now(UTC)
            for step in job["steps"]:
                if "uses" in step:
                    simulated_actions.append(step["uses"])
                else:
                    assert step["run"].startswith("echo ")
                    subprocess.run(
                        [sys.executable, "-c", "import sys; print(sys.argv[1])", step["run"][5:]],
                        check=True,
                        capture_output=True,
                        timeout=10,
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
            "html_url": f"https://example.invalid/fixture/runs/{run_id}",
            "fixture_simulated_actions": simulated_actions,
            "fixture_services_simulated": True,
        }

    def create_draft_pull_request(self, *args, **kwargs):
        self.drafts.append(kwargs)
        return {"html_url": "https://example.invalid/fixture/pull/1"}


@pytest.mark.parametrize("strategy", REGISTRY)
def test_real_cli_path_discovers_reviews_executes_reports_and_publishes_fixture(
    strategy,
    tmp_path,
    monkeypatch,
):
    baseline = FIXTURES[strategy]
    if strategy != "superseded_cancellation":
        extra_action = (
            "      - uses: actions/checkout@v4\n"
            if strategy == "setup_removal"
            else "      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'\n"
        )
        baseline += (
            "  independent:\n    runs-on: ubuntu-24.04\n    steps:\n"
            + extra_action
            + "      - run: echo independent\n"
        )
    github = FixtureGitHub(baseline)
    inference = FixtureInference(strategy)
    monkeypatch.setattr("ci_agent.cli.GitHubClient.from_git_credential", lambda: github)
    monkeypatch.setattr(
        "ci_agent.experiments.live_setup.CrusoeInference.from_env", lambda **_: inference
    )
    # Fail any accidental actual HTTP access, including upstream writes.
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        Mock(side_effect=AssertionError("No network in fixture")),
    )
    template = json.loads(Path("config/contract-request.example.json").read_text(encoding="utf-8"))
    template["context"]["required_checks"] = [
        {"name": name, "command": job["steps"][-1]["run"], "required": True}
        for name, job in parse(baseline)["jobs"].items()
    ]
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps(template))
    output = tmp_path / "agent"
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
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"
    audit = json.loads((output / "setup/proposal/proposal.json").read_text())
    report = json.loads((output / "execution/report.json").read_text())
    assert audit["proposal"]["optimization"] == strategy
    if strategy != "superseded_cancellation":
        assert len(audit["proposer_context"]["eligible_proposals"]) >= 2
    assert inference.calls == ["ContractRules", "ContractReview", "LiveProposal", "ProposalReview"]
    assert len(github.dispatched) == 2
    assert report["sample_pairs"] == 1
    assert report["baseline_passed"] and report["proposed_passed"]
    assert report["evidence_class"].startswith("FIXTURE_")
    assert report["timing"]["candidate"]["aggregate_runner_s"] > 0
    assert len(github.drafts) == 1
    assert strategy in github.drafts[0]["body"]
    assert not report["verified_optimization"]
    # Resume repeats neither inference, dispatch nor publication.
    resumed = CliRunner().invoke(main, args + ["--resume"])
    assert resumed.exit_code == 0, resumed.output
    assert len(github.dispatched) == 2
    assert len(github.drafts) == 1


@pytest.mark.parametrize("strategy", REGISTRY)
def test_independent_review_rejection_never_dispatches(strategy, tmp_path, monkeypatch):
    from ci_agent.contracts import ContractReview, SealedContract, contract_fingerprint
    from ci_agent.experiments.live_proposal import generate_live_proposal
    from ci_agent.models import RequiredCheck, SuccessContract

    class RejectingInference(FixtureInference):
        def complete_structured(self, **kwargs):
            if kwargs["output_model"] is ProposalReview:
                return ProposalReview(
                    approved=False, issues=("Needs more evidence",), rationale="Reject"
                )
            return super().complete_structured(**kwargs)

    contract = SuccessContract(
        goal_id="fixture",
        version=1,
        reviewed=True,
        required_checks=(RequiredCheck(name="tests"),),
        allowed_optimizations=(strategy,),
    )
    sealed = SealedContract(
        contract=contract,
        contract_fingerprint=contract_fingerprint(contract),
        review=ContractReview(approved=True, rationale="Fixture"),
    )
    output = tmp_path / "rejected"
    with pytest.raises(ValueError, match="Independent proposal review rejected"):
        generate_live_proposal(
            RejectingInference(strategy),
            repository="fixture/source",
            baseline=FIXTURES[strategy],
            sealed_contract=sealed,
            output=output,
        )
    assert (output / "proposal.json").exists()
    assert not (output / "candidate.yml").exists()
