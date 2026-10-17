"""Conservative, deterministic strategy discovery and independently replayable validation.

No repository annotations or model assertions count as soundness evidence. Each
generator proves eligibility from the complete workflow or returns no candidate.
"""

import re
import shlex
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

import yaml


def parse(raw):
    value = yaml.safe_load(raw)
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), dict) or not value["jobs"]:
        raise TypeError("Workflow must contain jobs")
    if True in value:
        value["on"] = value.pop(True)
    return value


@dataclass(frozen=True)
class Strategy:
    name: str
    evidence_requirement: str
    transform: Callable
    coverage_factory: Callable | None = None

    def propose(self, baseline):
        before = parse(baseline)
        after = deepcopy(before)
        evidence = self.transform(after)
        if not evidence or after == before:
            return None
        return {
            "optimization": self.name,
            "candidate_workflow": yaml.safe_dump(after, sort_keys=False),
            "evidence": evidence,
            "hypothesis": self.evidence_requirement,
            "risks": ["Eligibility is structural; timing benefit requires measurement."],
        }

    def validate(self, baseline, candidate):
        expected = self.propose(baseline)
        if expected is None or parse(candidate) != parse(expected["candidate_workflow"]):
            raise ValueError(
                f"{self.name}: candidate fails eligibility or exact transformation validation"
            )


def literal_job(job):
    """Prove no file, output, artifact, or action dependency: literal logging only."""
    if set(job) - {"name", "runs-on", "steps", "needs", "if", "timeout-minutes", "strategy"}:
        return False
    if job.get("runs-on") not in ("ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04"):
        return False
    if "strategy" in job:
        strategy = job["strategy"]
        if set(strategy) != {"matrix"} or not isinstance(strategy["matrix"], dict):
            return False
        if any(
            not isinstance(v, list) or not v or any(not isinstance(x, (str, int, float)) for x in v)
            for k, v in strategy["matrix"].items()
            if k != "exclude"
        ):
            return False
    return bool(job.get("steps")) and all(
        set(step) <= {"name", "run"}
        and isinstance(step.get("run"), str)
        and re.fullmatch(r"echo [A-Za-z0-9 ._-]+", step["run"])
        for step in job["steps"]
    )


def parallelism(value):
    if value.get("env") or value.get("defaults"):
        return []
    evidence = []
    for name, job in value["jobs"].items():
        # always() preserves execution after upstream failure. Literal jobs cannot
        # consume upstream outputs/artifacts or require success-dependent gating.
        if (
            job.get("needs")
            and job.get("if") in ("always()", "${{ always() }}")
            and literal_job(job)
        ):
            needs = job["needs"]
            needs = [needs] if isinstance(needs, str) else needs
            if all(n in value["jobs"] and literal_job(value["jobs"][n]) for n in needs):
                del job["needs"]
                evidence.append(
                    f"{name}: always() and all dependency endpoints contain literal logging only"
                )
    return evidence


def checkout(value):
    if value.get("env") or value.get("defaults"):
        return []
    evidence = []
    for name, job in value["jobs"].items():
        steps = job.get("steps", [])
        indices = [i for i, step in enumerate(steps) if step == {"uses": "actions/checkout@v4"}]
        if len(indices) != 1:
            continue
        probe = deepcopy(job)
        probe["steps"].pop(indices[0])
        if literal_job(probe):
            job["steps"].pop(indices[0])
            evidence.append(
                f"{name}: every remaining step is literal echo; no working-tree consumer"
            )
    return evidence


def setup(value):
    if value.get("env") or value.get("defaults"):
        return []
    evidence = []
    for name, job in value["jobs"].items():
        steps = job.get("steps", [])
        indices = [
            i
            for i, step in enumerate(steps)
            if set(step) == {"uses", "with"}
            and step["uses"] in ("actions/setup-node@v4", "actions/setup-python@v5")
            and set(step["with"])
            == ({"node-version"} if "node" in step["uses"] else {"python-version"})
            and isinstance(next(iter(step["with"].values())), str)
            and re.fullmatch(r"\d+(\.\d+)*", next(iter(step["with"].values())))
        ]
        if len(indices) != 1:
            continue
        probe = deepcopy(job)
        probe["steps"].pop(indices[0])
        if literal_job(probe):
            job["steps"].pop(indices[0])
            evidence.append(
                f"{name}: runtime setup has no consumer; all remaining steps are literal echo"
            )
    return evidence


CONCURRENCY = {
    "group": "${{ github.workflow }}-${{ github.event.pull_request.number }}",
    "cancel-in-progress": True,
}


def cancellation(value):
    if value.get("env") or value.get("defaults"):
        return []
    trigger = value.get("on", value.get(True))  # PyYAML YAML 1.1 boolean key
    pr_only = (
        trigger == "pull_request"
        or trigger == ["pull_request"]
        or (
            isinstance(trigger, dict)
            and set(trigger) == {"pull_request"}
            and trigger["pull_request"] in (None, {})
        )
    )
    if not pr_only or "concurrency" in value:
        return []
    # Deployments, reusable workflows and privileged actions need lifecycle evidence.
    if not all(literal_job(j) for j in value["jobs"].values()):
        return []
    value["concurrency"] = deepcopy(CONCURRENCY)
    # Dispatch experiments must never cancel unrelated runs with a missing PR number.
    value["concurrency"]["group"] = (
        "${{ github.workflow_ref }}-${{ github.event.pull_request.number || github.run_id }}"
    )
    return [
        "PR-only workflow; literal logging jobs have no deployment or cleanup side effects; group is per workflow and PR"
    ]


def readiness(value):
    evidence = []
    for name, job in value["jobs"].items():
        for service in job.get("services", {}).values():
            options = service.get("options", "")
            try:
                tokens = shlex.split(options)
            except (ValueError, TypeError):
                continue
            flags = ("--health-cmd", "--health-interval", "--health-retries", "--health-timeout")
            if any(tokens.count(flag) != 1 for flag in flags):
                continue
            if any(tokens.index(flag) + 1 >= len(tokens) for flag in flags):
                continue
            if tokens[tokens.index("--health-cmd") + 1] != "pg_isready":
                continue
            interval = re.search(r"--health-interval (\d+)s\b", options)
            retries = re.search(r"--health-retries (\d+)\b", options)
            if (
                str(service.get("image", "")).startswith("postgres:")
                and interval
                and retries
                and int(interval[1]) > 1
                and int(retries[1]) > 0
                and "--health-cmd " in options
                and "--health-timeout " in options
            ):
                options = options[: interval.start(1)] + "1" + options[interval.end(1) :]
                service["options"] = re.sub(
                    r"--health-retries \d+\b",
                    f"--health-retries {int(interval[1]) * int(retries[1])}",
                    options,
                )
                evidence.append(
                    f"{name}: explicit PostgreSQL probe with interval {interval[1]}s and retries {retries[1]}"
                )
    return evidence


REGISTRY = {
    s.name: s
    for s in (
        Strategy(
            "parallelism",
            "Remove only proven independent DAG gates; may reduce critical path, not runner time.",
            parallelism,
        ),
        Strategy(
            "checkout_reduction",
            "Remove checkout only with exhaustive proof of no working-tree consumers.",
            checkout,
        ),
        Strategy(
            "setup_removal",
            "Remove runtime setup only with exhaustive proof of no runtime consumers.",
            setup,
        ),
        Strategy(
            "superseded_cancellation",
            "Cancel obsolete PR runs only with proven absence of persistent side effects.",
            cancellation,
        ),
        Strategy(
            "service_readiness",
            "Poll the identical probe faster with the same nominal retry budget; slow probes may extend failure time.",
            readiness,
        ),
    )
}

RECOMMENDATIONS = {
    "job_batching": "Requires equivalent check-identity mapping and isolation/setup compatibility evidence.",
    "sharding_balancing": "Requires exhaustive test inventory, disjoint complete partition and duration history.",
    "scoped_installs": "Requires dependency closure and lifecycle-script equivalence evidence.",
    "runner_selection": "Requires authorized infrastructure and matched workload benchmarks; no paid migration.",
    "tool_replacement": "Requires diagnostic/rule equivalence and side-by-side full-coverage execution.",
    "selective_tests": "Requires sound dependency analysis and equivalent full required coverage.",
}


def discover(baseline, allowed=None):
    allowed = set(REGISTRY if allowed is None else allowed)
    proposals, rejected = [], {}
    for name, strategy in REGISTRY.items():
        proposal = strategy.propose(baseline) if name in allowed else None
        if proposal:
            proposals.append(proposal)
        else:
            rejected[name] = (
                "Contract does not permit strategy"
                if name not in allowed
                else "No structurally proven eligible change: " + strategy.evidence_requirement
            )
    return proposals, rejected


def validate_strategy(name, baseline, candidate):
    if name not in REGISTRY:
        raise ValueError(f"Unsupported optimization: {name}")
    REGISTRY[name].validate(baseline, candidate)


def validated_coverage(name, baseline, candidate):
    """Derive coverage from a fresh strategy validation, never saved report claims."""
    validate_strategy(name, baseline, candidate)
    if REGISTRY[name].coverage_factory:
        return REGISTRY[name].coverage_factory(baseline, candidate)
    from ci_agent.experiments.live_loop import count_workflow_jobs

    before = count_workflow_jobs(baseline, list(parse(baseline)["jobs"]))
    after = count_workflow_jobs(candidate, list(parse(candidate)["jobs"]))
    if before != after:
        raise ValueError("Job count change requires a strategy-certified coverage plan")
    return before
