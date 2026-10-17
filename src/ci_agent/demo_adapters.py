"""Clearly simulated adapters for the local BRO-31 demonstration.

These adapters return invented example data and never contact GitHub, Crusoe,
or any runner service. They exist to exercise the shared interfaces end to end.
"""

from __future__ import annotations

from dataclasses import dataclass

from ci_agent.workflows.dependency_graph import build_dep_graph, critical_path


@dataclass(frozen=True)
class SimulatedRun:
    run_id: str
    runner_minutes: float
    wall_clock_minutes: float
    checks: dict[str, str]
    telemetry: dict[str, float]


class DemoAdapters:
    """Deterministic fixtures for the local experiment walkthrough."""

    label = "SIMULATED EXAMPLE - not a real GitHub run or measured result"
    def __init__(self, required_checks: tuple[str, ...] = ("tests", "lint")) -> None:
        self.required_checks = required_checks

    def observe(self) -> dict[str, object]:
        workflow_yaml = """
jobs:
  install:
    runs-on: ubuntu-latest
  tests:
    needs: install
  lint:
    needs: install
"""
        dependencies = build_dep_graph(workflow_yaml)
        path = critical_path(dependencies, {"install": 3.0, "tests": 5.0, "lint": 2.0})
        return {
            "workflow": "example-ci.yml",
            "source_revision": "example-sha-001",
            "completed_run": "example-run-100",
            "runner_minutes": 10.0,
            "required_checks": list(self.required_checks),
            "job_dependencies": dependencies,
            "estimated_critical_path_example": path,
            "reason": "Package installation is repeated in each job.",
        }

    def propose(self) -> dict[str, object]:
        return {
            "change": "Cache downloaded Python packages using the lockfile as the cache key.",
            "hypothesis": "Reusing downloaded packages will reduce runner minutes.",
            "expected_effect": "Fewer package download minutes; all checks remain enabled.",
            "patch": "SIMULATED diff: add lockfile-keyed dependency cache to example-ci.yml",
            "affected_paths": [".github/workflows/example-ci.yml"],
        }

    def validate(self, *, fail_check: bool = False) -> dict[str, object]:
        return {
            "allowed_change": True,
            "required_checks_preserved": True,
            "patch_applies": True,
            "safety_rules_passed": True,
            "reason": "The example edit adds caching and leaves required checks unchanged.",
            "would_fail_during_execution": fail_check,
        }

    def compare(self, index: int, *, fail_check: bool = False) -> tuple[SimulatedRun, SimulatedRun]:
        baseline = SimulatedRun(
            run_id=f"example-baseline-{index}",
            runner_minutes=10.0,
            wall_clock_minutes=6.0,
            checks={check: "success" for check in self.required_checks},
            telemetry={"cpu_utilization_percent": 41.0, "memory_utilization_percent": 52.0},
        )
        candidate_checks = {check: "success" for check in self.required_checks}
        if fail_check and index == 1:
            candidate_checks["tests"] = "failure"
        candidate = SimulatedRun(
            run_id=f"example-candidate-{index}",
            runner_minutes=9.2,
            wall_clock_minutes=5.8,
            checks=candidate_checks,
            telemetry={"cpu_utilization_percent": 44.0, "memory_utilization_percent": 54.0},
        )
        return baseline, candidate
