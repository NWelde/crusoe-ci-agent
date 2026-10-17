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

from ci_agent.workflows.matrix import matrix_cells
from ci_agent.workflows.usage import EFFECT, HISTORY, SETUP_RUNTIME, job_usage, step_usage


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

    def propose(self, baseline, source_evidence=None):
        before = parse(baseline)
        after = deepcopy(before)
        evidence = self.transform(after, source_evidence or {})
        if not evidence or after == before:
            return None
        return {
            "optimization": self.name,
            "candidate_workflow": yaml.safe_dump(after, sort_keys=False),
            "evidence": evidence,
            "hypothesis": self.evidence_requirement,
            "risks": ["Eligibility is structural; timing benefit requires measurement."],
        }

    def validate(self, baseline, candidate, source_evidence=None):
        expected = self.propose(baseline, source_evidence)
        if expected is None or parse(candidate) != parse(expected["candidate_workflow"]):
            raise ValueError(
                f"{self.name}: candidate fails eligibility or exact transformation validation"
            )


def safe_context(value, job):
    """Accept ordinary CI environment/defaults, reject hidden execution hooks."""
    for scope in (value, job, *job.get("steps", [])):
        env = scope.get("env", {})
        if not isinstance(env, dict) or any(
            k.upper()
            in {
                "BASH_ENV",
                "ENV",
                "SHELLOPTS",
                "BASHOPTS",
                "NODE_OPTIONS",
                "PYTHONSTARTUP",
            }
            for k in env
        ):
            return False
        defaults = scope.get("defaults", {}).get("run", {})
        if defaults.get("shell", "bash") not in ("bash", "sh"):
            return False
    return True


def isolated_runner(job):
    runner = job.get("runs-on")
    if isinstance(runner, str) and re.fullmatch(
        r"(ubuntu|windows|macos)-(latest|[0-9.]+)(-arm)?", runner
    ):
        return True
    if runner == "${{ matrix.os }}":
        matrix = job.get("strategy", {}).get("matrix", {})
        try:
            cells = matrix_cells(matrix)
        except ValueError:
            return False
        return bool(cells) and all(isolated_runner({"runs-on": cell.get("os")}) for cell in cells)
    return False


def ci_job(value, job, sources):
    """Classify ordinary build/lint/test jobs rather than requiring echo commands."""
    if not job.get("steps") or not isolated_runner(job) or not safe_context(value, job):
        return None
    if any(k in job for k in ("environment", "uses", "container")):
        return None
    if EFFECT.search(str(value.get("env", {}))):
        return None
    permissions = job.get("permissions", value.get("permissions", {}))
    if permissions == "write-all" or (
        isinstance(permissions, dict) and "write" in permissions.values()
    ):
        return None
    usage = job_usage(job, sources.get("files", {}), value.get("defaults"))
    if usage.unsafe or usage.unknown:
        return None
    return usage


def parallelism(value, sources=None):
    sources = sources or {}
    evidence = []
    for name, job in value["jobs"].items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        if not needs or job.get("if") not in (
            "always()",
            "${{ always() }}",
            "!cancelled()",
            "${{ !cancelled() }}",
        ):
            continue
        endpoints = [job, *(value["jobs"].get(n, {}) for n in needs)]
        usages = [ci_job(value, endpoint, sources) for endpoint in endpoints]
        # Isolated job workspaces are not shared, but artifacts, outputs, secrets,
        # explicit needs references and lifecycle effects are real dependencies.
        text = str(endpoints)
        if any(u is None for u in usages) or re.search(
            r"needs\s*[.\[]|download-artifact|upload-artifact|secrets[.\[]", text, re.IGNORECASE
        ):
            continue
        if any(endpoint.get("outputs") for endpoint in endpoints):
            continue
        if any(
            endpoint.get("concurrency")
            or any(
                re.search(r"\b(?:success|failure|cancelled)\s*\(", str(step.get("if", "")))
                for step in endpoint.get("steps", [])
            )
            for endpoint in endpoints
        ):
            continue
        del job["needs"]
        evidence.append(
            f"{name}: failure-independent condition retained; hosted isolated workspaces; no upstream outputs/artifacts or lifecycle consumers"
        )
        evidence.extend(item for usage in usages for item in usage.evidence)
    return evidence


def action_base(step):
    return str(step.get("uses", "")).split("@")[0].lower()


def checkout(value, sources=None):
    sources = sources or {}
    files = sources.get("files", {})
    evidence = []
    for name, job in value["jobs"].items():
        if not safe_context(value, job):
            continue
        steps = job.get("steps", [])
        # Redundant checkout elimination is command-agnostic: arbitrary real
        # build/test steps after the retained checkout are unchanged.
        for i in range(len(steps) - 2, -1, -1):
            first, second = steps[i], steps[i + 1]
            if (
                action_base(first) == "actions/checkout"
                and "id" not in first
                and {k: v for k, v in first.items() if k != "name"}
                == {k: v for k, v in second.items() if k != "name"}
            ):
                steps.pop(i)
                evidence.append(
                    f"{name}: adjacent identical checkout has no intervening consumer; retained checkout and all build/test commands unchanged"
                )
        indices = [i for i, step in enumerate(steps) if action_base(step) == "actions/checkout"]
        if len(indices) != 1:
            continue
        index = indices[0]
        step = steps[index]
        probe = deepcopy(job)
        probe["steps"].pop(index)
        usage = job_usage(probe, files, value.get("defaults"))
        if (
            not usage.workspace
            and not usage.unknown
            and not usage.history
            and "id" not in step
            and set(step) <= {"uses", "name"}
        ):
            steps.pop(index)
            evidence.append(f"{name}: no remaining command/action reads the checkout working tree")
            continue
        options = step.get("with", {})
        # A shallow candidate retains checkout, all repository files and all
        # commands. Full-source and command/config evidence rules out known
        # history consumers; complete baseline/candidate checks must still pass.
        if (
            str(options.get("fetch-depth")) == "0"
            and sources.get("complete")
            and not usage.history
            and not usage.unknown
            and not any(HISTORY.search(content) for content in files.values())
            and not any(
                key in options
                for key in ("ref", "repository", "submodules", "lfs", "sparse-checkout")
            )
        ):
            step["with"]["fetch-depth"] = 1
            evidence.append(
                f"{name}: full source inventory and resolved commands/configuration contain no known Git-history/versioning consumer; preserve working tree and use depth 1"
            )
            evidence.extend(usage.evidence)
    return evidence


def setup(value, sources=None):
    sources = sources or {}
    files = sources.get("files", {})
    evidence = []
    for name, job in value["jobs"].items():
        if not safe_context(value, job):
            continue
        steps = job.get("steps", [])
        for index in range(len(steps) - 1, -1, -1):
            step = steps[index]
            base = action_base(step)
            runtime = SETUP_RUNTIME.get(base)
            # Caches, outputs, custom installation hooks and conditions can be
            # observable. Preserve them; only plain runtime selection is eligible.
            allowed = {
                "node-version",
                "python-version",
                "go-version",
                "java-version",
                "distribution",
                "ruby-version",
            }
            if (
                runtime is None
                or "id" in step
                or set(step) - {"uses", "with", "name"}
                or not step.get("with")
                or set(step["with"]) - allowed
            ):
                continue
            later = None
            consumed = False
            for other in steps[index + 1 :]:
                if action_base(other) == base and not other.get("if"):
                    later = other
                    break
                usage = step_usage(
                    other,
                    files,
                    job.get("defaults", value.get("defaults", {}))
                    .get("run", {})
                    .get("working-directory", ""),
                )
                if usage.unknown or runtime in usage.runtimes:
                    consumed = True
                    break
            if later is not None and not consumed:
                steps.pop(index)
                evidence.append(
                    f"{name}: {base} selection is overwritten by a later unconditional setup before any {runtime} consumer; final setup and arbitrary build/test commands retained"
                )
                continue
            probe = deepcopy(job)
            probe["steps"].pop(index)
            usage = job_usage(probe, files, value.get("defaults"))
            if (
                sources.get("complete")
                and not usage.unknown
                and runtime not in usage.runtimes
                and not any(
                    re.search(r"\b" + re.escape(runtime) + r"\b", content, re.IGNORECASE)
                    for content in files.values()
                )
            ):
                steps.pop(index)
                evidence.append(
                    f"{name}: source inventory and resolved commands use {sorted(usage.runtimes)}; no {runtime} consumer or setup output/cache"
                )
            elif not usage.unknown and not usage.runtimes and not usage.workspace:
                steps.pop(index)
                evidence.append(f"{name}: no remaining command/action consumes runtime setup")
    return evidence


CONCURRENCY = {
    "group": "${{ github.workflow_ref }}-${{ github.event_name }}-${{ github.event.pull_request.number || (github.event_name == 'push' && github.ref) || github.run_id }}",
    "cancel-in-progress": True,
}


def cancellation(value, sources=None):
    sources = sources or {}
    trigger = value.get("on")
    events = set(trigger) if isinstance(trigger, (dict, list)) else {trigger}
    if not events.intersection({"pull_request", "push"}) or "concurrency" in value:
        return []
    # PR validation can be cancelled; pushes, schedules, dispatches, release
    # workflows and privileged lifecycle jobs remain unaffected.
    if "pull_request_target" in events or any(
        ci_job(value, job, sources) is None for job in value["jobs"].values()
    ):
        return []
    if EFFECT.search(str(value.get("env", {}))):
        return []
    value["concurrency"] = deepcopy(CONCURRENCY)
    if events != {"pull_request"}:
        value["concurrency"]["cancel-in-progress"] = (
            "${{ github.event_name == 'pull_request' || (github.event_name == 'push' && github.ref_type == 'branch') }}"
        )
    evidence = [
        "Resolved build/test/install commands and known actions; no deployments, write permissions, secret consumers or unrecognized lifecycle commands; only obsolete runs of the same PR or pushed branch/event/workflow can cancel; tag/scheduled/dispatched runs are preserved"
    ]
    for job in value["jobs"].values():
        evidence.extend(job_usage(job, sources.get("files", {}), value.get("defaults")).evidence)
    return evidence


def readiness(value, sources=None):
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
            "Reduce checkout duplication/history only with command and source-usage evidence.",
            checkout,
        ),
        Strategy(
            "setup_removal",
            "Remove overwritten or unused runtime setup while preserving all build/test commands.",
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


def discover(baseline, allowed=None, source_evidence=None):
    allowed = set(REGISTRY if allowed is None else allowed)
    proposals, rejected = [], {}
    for name, strategy in REGISTRY.items():
        proposal = strategy.propose(baseline, source_evidence) if name in allowed else None
        if proposal:
            proposals.append(proposal)
        else:
            diagnostics = []
            value = parse(baseline)
            for job_name, job in value["jobs"].items():
                usage = job_usage(
                    job, (source_evidence or {}).get("files", {}), value.get("defaults")
                )
                if usage.unknown:
                    diagnostics.append(
                        f"{job_name}: unresolved command/action or missing script evidence"
                    )
                    diagnostics.extend(usage.evidence)
                if usage.history and name == "checkout_reduction":
                    diagnostics.append(f"{job_name}: Git-history consumer detected")
                if (
                    name == "parallelism"
                    and job.get("needs")
                    and job.get("if")
                    not in ("always()", "${{ always() }}", "!cancelled()", "${{ !cancelled() }}")
                ):
                    diagnostics.append(f"{job_name}: preserve success/failure dependency gate")
            rejected[name] = (
                "Contract does not permit strategy"
                if name not in allowed
                else "No structurally proven eligible change: "
                + strategy.evidence_requirement
                + (" Details: " + "; ".join(dict.fromkeys(diagnostics)) if diagnostics else "")
            )
    return proposals, rejected


def validate_strategy(name, baseline, candidate, source_evidence=None):
    if name not in REGISTRY:
        raise ValueError(f"Unsupported optimization: {name}")
    REGISTRY[name].validate(baseline, candidate, source_evidence)


def validated_coverage(name, baseline, candidate, source_evidence=None):
    """Derive coverage from a fresh strategy validation, never saved report claims."""
    validate_strategy(name, baseline, candidate, source_evidence)
    if REGISTRY[name].coverage_factory:
        return REGISTRY[name].coverage_factory(baseline, candidate)
    from ci_agent.experiments.live_loop import count_workflow_jobs

    before = count_workflow_jobs(baseline, list(parse(baseline)["jobs"]))
    after = count_workflow_jobs(candidate, list(parse(candidate)["jobs"]))
    if before != after:
        raise ValueError("Job count change requires a strategy-certified coverage plan")
    return before
