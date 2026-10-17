"""Bounded live parallelism experiments with fail-closed evidence collection."""

from __future__ import annotations

import itertools
import json
import time
import zipfile
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime

import requests
import yaml

from ci_agent.contracts import load_contract
from ci_agent.github.fork_experiment import (
    PreparedFork,
    _add_dispatch,
    _content_text,
    prepare_fork_experiment,
)


def workflow(raw):
    value = yaml.safe_load(raw)
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), dict):
        raise TypeError("Workflow must contain jobs")
    return value


def count_workflow_jobs(raw, checks):
    jobs = workflow(raw)["jobs"]
    if not set(checks).issubset(jobs):
        raise ValueError("Required checks must identify workflow job IDs")
    expected = 0
    for name in checks:
        matrix = jobs[name].get("strategy", {}).get("matrix", {})
        if not isinstance(matrix, dict) or "include" in matrix:
            raise ValueError("Dynamic/include matrices are not supported yet")
        axes = {k: v for k, v in matrix.items() if k != "exclude"}
        if any(not isinstance(v, list) or not v for v in axes.values()):
            raise ValueError("Matrix axes must be nonempty static lists")
        cells = [
            dict(zip(axes, values, strict=True)) for values in itertools.product(*axes.values())
        ]
        expected += sum(
            not any(
                all(cell.get(k) == v for k, v in rule.items()) for rule in matrix.get("exclude", [])
            )
            for cell in cells
        )
    return expected


def validate_parallelism(baseline, candidate, checks):
    """Allow only removal of job dependencies; preserve every executable step."""
    before, after = workflow(baseline), workflow(candidate)
    if not set(checks).issubset(before["jobs"]):
        raise ValueError("Required checks must identify workflow job IDs")
    expected = count_workflow_jobs(baseline, checks)
    changed = False
    for name, job in before["jobs"].items():
        other = after["jobs"].get(name)
        if not isinstance(other, dict):
            raise TypeError("Jobs cannot be removed")
        old_needs, new_needs = job.get("needs", []), other.get("needs", [])
        old_needs = [old_needs] if isinstance(old_needs, str) else old_needs
        new_needs = [new_needs] if isinstance(new_needs, str) else new_needs
        if not set(new_needs).issubset(old_needs):
            raise ValueError("Only removing dependencies is supported")
        changed |= old_needs != new_needs
        job.pop("needs", None)
        other.pop("needs", None)
    if before != after or not changed:
        raise ValueError("Candidate must change only job dependencies")
    return expected


def evaluate_pair(baseline, candidate, expected):
    """Require complete successful runs and identical job coverage before timing."""
    totals = []
    for run in (baseline, candidate):
        jobs = run.get("jobs", [])
        if (
            run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or len(jobs) != expected
            or len({j["id"] for j in jobs}) != expected
            or any(j.get("conclusion") != "success" for j in jobs)
        ):
            raise ValueError("Required checks failed or complete job coverage is missing")
        durations = [
            (
                datetime.fromisoformat(j["completed_at"]) - datetime.fromisoformat(j["started_at"])
            ).total_seconds()
            for j in jobs
        ]
        if any(d < 0 for d in durations) or sum(durations) <= 0:
            raise ValueError("Invalid job durations")
        totals.append(sum(durations) / 60)
    if Counter(j["name"] for j in baseline["jobs"]) != Counter(
        j["name"] for j in candidate["jobs"]
    ):
        raise ValueError("Baseline and candidate job coverage differs")
    return {
        "baseline_minutes": totals[0],
        "candidate_minutes": totals[1],
        "reduction_percent": 100 * (totals[0] - totals[1]) / totals[0],
    }


def verify_cache_conditions(client, report, output, expected):
    """Attach explicit cache observations; unverified savings cannot authorize adoption."""
    from ci_agent.experiments.live_cache import audit_run_caches, compare_pair_caches

    pairs = []
    try:
        for index in range(1, 4):
            audits = []
            for variant in ("baseline", "candidate"):
                receipt = next(
                    r for r in report["runs"] if r["pair"] == index and r["variant"] == variant
                )
                run_id = receipt["run_id"]
                path = output / f"cache-{run_id}.json"
                audit = (
                    json.loads(path.read_text(encoding="utf-8"))
                    if path.exists()
                    else audit_run_caches(
                        client, report["fork"]["owner"], report["fork"]["name"], run_id, output
                    )
                )
                if audit["run_id"] != run_id:
                    raise ValueError("Cache audit run ID differs")
                audits.append(audit)
            pairs.append(compare_pair_caches(*audits, expected))
        report["cache_verification"] = {"matched": all(p["matched"] for p in pairs), "pairs": pairs}
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        StopIteration,
        requests.RequestException,
        zipfile.BadZipFile,
    ) as exc:
        report["cache_verification"] = {
            "matched": False,
            "pairs": pairs,
            "reason": f"Cache audit unavailable ({type(exc).__name__})",
        }
    report["practical_outcome"] = report["outcome"]
    if not report["cache_verification"]["matched"]:
        report.update(
            outcome="inconclusive",
            reason="Measured effects require matched cache evidence before a practical verdict",
        )
    return report


def run_live(client, **options):
    """Own an exclusive evidence-directory lock across dispatch and collection."""
    output = options["output"]
    output.mkdir(parents=True, exist_ok=options.get("resume", False))
    lock_path = output / "run.lock"
    try:
        lock = lock_path.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError(
            "Experiment is locked by another process; reconcile run.lock first"
        ) from None
    try:
        with lock:
            lock.write(datetime.now(UTC).isoformat())
            lock.flush()
            return _run_live(client, **options)
    finally:
        lock_path.unlink(missing_ok=True)


def _run_live(
    client,
    *,
    repository,
    workflow_path,
    candidate_path,
    contract_path,
    output,
    run_key,
    existing_fork=None,
    common_source_files=None,
    source_revision=None,
    optimization="parallelism",
    resume=False,
    prepared_fork=None,
    baseline_run_id=None,
    evaluation_mode="research",
):
    """Run one supplied proposal. Existing output blocks accidental redispatch."""
    sealed = load_contract(contract_path)
    contract = sealed.contract
    if contract.minimum_samples != 3 or optimization not in contract.allowed_optimizations:
        raise ValueError("Live execution requires three pairs and a permitted optimization")
    if contract.metric != "required_runner_minutes":
        raise ValueError("Unsupported contract metric")
    report = {
        "evidence_class": "LIVE_GITHUB_ACTIONS_RUNS",
        "status": "preflight",
        "contract": sealed.model_dump(mode="json"),
        "pairs": [],
        "runs": [],
        "started_at": datetime.now(UTC).isoformat(),
        "evaluation_mode": evaluation_mode,
        "measurement_policy": (
            "One-pair Shadow Runner demo policy; sealed contract is a workflow-safety reference."
            if evaluation_mode == "shadow"
            else "Sealed three-pair research policy"
        ),
        "inputs": {
            "repository": repository,
            "workflow_path": workflow_path,
            "candidate": candidate_path.read_text(encoding="utf-8"),
            "contract": sealed.contract_fingerprint,
            "common_source_files": common_source_files or {},
            "source_revision": source_revision,
            "optimization": optimization,
            "existing_fork": existing_fork,
            "run_key": run_key,
            "prepared_fork": prepared_fork,
            "baseline_run_id": baseline_run_id,
        },
    }
    if resume:
        previous = json.loads((output / "report.json").read_text(encoding="utf-8"))
        if previous.get("evaluation_mode", "research") != evaluation_mode:
            raise ValueError("Resume cannot change evaluation mode; create a separate demo report")
        if previous.get("inputs") != report["inputs"]:
            raise ValueError("Resume inputs differ from the saved experiment")
        if previous.get("status") == "completed":
            return previous
        report = previous

    def save():
        temporary = output / "report.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")
        from ci_agent.reporting.live_report import write_live_report

        write_live_report(output, report)

    save()
    elapsed = (datetime.now(UTC) - datetime.fromisoformat(report["started_at"])).total_seconds()
    deadline = time.monotonic() + contract.max_experiment_minutes * 60 - elapsed

    def remaining():
        seconds = int(deadline - time.monotonic())
        if seconds <= 0:
            raise TimeoutError("Experiment time budget exhausted")
        return seconds

    try:
        owner, repo = repository.split("/")
        _, sha = client.default_branch(owner, repo)
        sha = report.get("upstream_source_sha") or source_revision or sha
        report["upstream_source_sha"] = sha
        save()
        baseline = _content_text(client.get_contents(owner, repo, workflow_path, sha))
        candidate = candidate_path.read_text(encoding="utf-8")
        checks = [c.name for c in contract.required_checks]
        for check in contract.required_checks:
            job = workflow(baseline)["jobs"].get(check.name, {})
            commands = [step.get("run", "").strip() for step in job.get("steps", [])]
            if not check.command or any(
                part.strip() not in commands for part in check.command.split("&&")
            ):
                raise ValueError("Contract commands do not match the target workflow")
        # All workflow jobs must be measured, including any undeclared helper jobs.
        if optimization == "service_readiness":
            from ci_agent.experiments.live_proposal import validate_service_polling

            validate_service_polling(baseline, candidate)
            expected = count_workflow_jobs(baseline, list(workflow(baseline)["jobs"]))
        else:
            expected = validate_parallelism(baseline, candidate, list(workflow(baseline)["jobs"]))
            validate_parallelism(baseline, candidate, checks)
        (output / "baseline.yml").write_text(baseline, encoding="utf-8")
        (output / "candidate.yml").write_text(candidate, encoding="utf-8")

        def progress(event):
            report.setdefault("preparation", []).append(event)
            save()

        if resume and not report.get("fork"):
            raise ValueError("Preparation was interrupted; reconcile saved branch receipts first")
        if prepared_fork and not report.get("fork"):
            prepared = PreparedFork(**prepared_fork)
            identity = client.authenticated_user()["login"]
            if (
                prepared.upstream != repository
                or prepared.repository != existing_fork
                or prepared.owner.casefold() != identity.casefold()
                or prepared.workflow_path != workflow_path
            ):
                raise ValueError("Prepared fork provenance does not match this experiment")
            actual = _content_text(
                client.get_contents(
                    prepared.owner, prepared.name, workflow_path, prepared.baseline_sha
                )
            )
            if workflow(actual) != workflow(_add_dispatch(baseline)):
                raise ValueError("Prepared baseline workflow differs from inspected source")
            for path, content in (common_source_files or {}).items():
                actual = _content_text(
                    client.get_contents(prepared.owner, prepared.name, path, prepared.base_sha)
                )
                if actual != content:
                    raise ValueError("Prepared baseline repairs differ from supplied repairs")
            progress(
                {
                    "stage": "prepared_fork_reused",
                    "baseline_sha": prepared.baseline_sha,
                    "baseline_run_id": baseline_run_id,
                }
            )
            current = client.get_contents(
                prepared.owner, prepared.name, workflow_path, prepared.candidate_branch
            )
            if workflow(_content_text(current)) != workflow(_add_dispatch(baseline)):
                raise ValueError("Prepared candidate branch was already changed; reconcile first")
            updated = client.put_file(
                prepared.owner,
                prepared.name,
                workflow_path,
                _add_dispatch(candidate),
                f"ci-agent: reviewed candidate {run_key}",
                prepared.candidate_branch,
                existing_sha=current["sha"],
            )
            prepared = replace(prepared, candidate_sha=updated["commit"]["sha"])
            report["fork"] = prepared.__dict__
            if baseline_run_id:
                known = client.get_run(prepared.owner, prepared.name, baseline_run_id)
                if known.get("head_sha") != prepared.baseline_sha or str(
                    known.get("workflow_id")
                ) != str(prepared.workflow_id):
                    raise ValueError("Qualification run does not match prepared baseline")
                report["runs"].append(
                    {
                        "pair": 1,
                        "variant": "baseline",
                        "branch": prepared.baseline_branch,
                        "status": "dispatched",
                        "at": known["created_at"],
                        "run_id": baseline_run_id,
                        "source": "reused exact baseline qualification run",
                    }
                )
            save()
        fork = (
            PreparedFork(**report["fork"])
            if report.get("fork")
            else prepare_fork_experiment(
                client,
                repository,
                workflow_path,
                candidate,
                run_key=run_key,
                source_sha=sha,
                timeout_seconds=min(120, remaining()),
                on_progress=progress,
                existing_fork=existing_fork,
                common_source_files=common_source_files,
            )
        )
        report.update(fork=fork.__dict__, status="running")
        report.pop("reason", None)
        report.pop("outcome", None)
        if not report.get("source_verification"):
            comparisons = []
            for variant, revision in (
                ("baseline", fork.baseline_sha),
                ("candidate", fork.candidate_sha),
            ):
                comparison = client._get(
                    f"/repos/{fork.owner}/{fork.name}/compare/{fork.base_sha}...{revision}"
                )
                paths = [file["filename"] for file in comparison.get("files", [])]
                if comparison.get("status") != "ahead" or paths != [workflow_path]:
                    raise ValueError(
                        "Variant changed files outside its workflow after common preparation"
                    )
                comparisons.append({"variant": variant, "revision": revision, "paths": paths})
            report["source_verification"] = {
                "shared_source_sha": fork.base_sha,
                "workflow_only_differences": comparisons,
            }
        save()
        raw_pairs = []
        report["pairs"] = []
        pair_count = 1 if evaluation_mode == "shadow" else contract.max_run_pairs
        for index in range(1, pair_count + 1):
            pair = []
            for variant, branch, revision in (
                ("baseline", fork.baseline_branch, fork.baseline_sha),
                ("candidate", fork.candidate_branch, fork.candidate_sha),
            ):
                receipt = next(
                    (r for r in report["runs"] if r["pair"] == index and r["variant"] == variant),
                    None,
                )
                if receipt and receipt.get("status") == "collected":
                    run = receipt["evidence"]
                    if run.get("head_sha") != revision:
                        raise ValueError("Saved run revision does not match prepared branch")
                    if evaluation_mode != "shadow":
                        evaluate_pair(run, run, expected)
                    pair.append(run)
                    continue
                dispatched = datetime.now(UTC)
                # Persist intent first. An interrupted dispatch must be reconciled manually.
                fresh = receipt is None
                receipt = receipt or {
                    "pair": index,
                    "variant": variant,
                    "branch": branch,
                    "status": "dispatch_pending",
                    "at": dispatched.isoformat(),
                }
                if fresh:
                    report["runs"].append(receipt)
                save()
                remaining()
                if fresh:
                    client.dispatch_workflow(fork.owner, fork.name, fork.workflow_id, branch)
                if receipt.get("run_id"):
                    appeared = {"id": receipt["run_id"]}
                elif not fresh:
                    matches = [
                        r
                        for r in client.find_dispatch_run(
                            fork.owner, fork.name, fork.workflow_id, branch
                        )
                        if r.get("head_sha") == revision
                        and datetime.fromisoformat(r["created_at"])
                        >= datetime.fromisoformat(receipt["at"]).replace(microsecond=0)
                    ]
                    if len(matches) != 1:
                        raise ValueError("Ambiguous pending dispatch; no duplicate was dispatched")
                    appeared = matches[0]
                else:
                    appeared = client.wait_for_dispatch_run(
                        fork.owner,
                        fork.name,
                        fork.workflow_id,
                        branch,
                        revision,
                        dispatched_after=dispatched.replace(microsecond=0),
                        timeout_seconds=min(240, remaining()),
                    )
                receipt.update(run_id=appeared["id"], status="dispatched")
                save()
                client.wait_for_run_completion(
                    fork.owner, fork.name, appeared["id"], timeout_seconds=remaining()
                )
                run = client.full_run(fork.owner, fork.name, appeared["id"])
                receipt.update(status="collected", evidence=run)
                failures = [
                    {
                        "job_id": job["id"],
                        "name": job["name"],
                        "conclusion": job.get("conclusion"),
                        "failed_steps": [
                            s["name"]
                            for s in job.get("steps", [])
                            if s.get("conclusion") == "failure"
                        ],
                    }
                    for job in run.get("jobs", [])
                    if job.get("conclusion") != "success"
                ]
                if failures:
                    report["failed_checks"] = failures
                save()
                if run.get("head_sha") != revision:
                    raise ValueError("Run source revision does not match prepared branch")
                if evaluation_mode != "shadow":
                    evaluate_pair(run, run, expected)
                pair.append(run)
            if evaluation_mode == "shadow":
                from ci_agent.experiments.shadow_mode import evaluate_shadow_pair

                report["pairs"].append(evaluate_shadow_pair(*pair, expected))
            else:
                report["pairs"].append(evaluate_pair(*pair, expected))
            raw_pairs.append({"baseline": pair[0], "candidate": pair[1]})
            save()
        from ci_agent.experiments.live_evaluation import evaluate_experiment

        if evaluation_mode == "shadow":
            report.update(report["pairs"][0])
        else:
            report.update(evaluate_experiment(raw_pairs, contract, expected_jobs=expected))
            verify_cache_conditions(client, report, output, expected)
        report.update(status="completed", publication="No PR created; human review required")
    except Exception as exc:
        report.update(status="stopped", outcome="void", reason=str(exc))
        save()
        raise
    save()
    return report
