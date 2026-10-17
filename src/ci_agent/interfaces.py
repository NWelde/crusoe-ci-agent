"""Typed boundaries between the CI agent components.

Protocols describe what an implementation must provide; they keep components
replaceable without each inventing a different message format.
"""

from __future__ import annotations

from typing import Protocol

from ci_agent.models import (
    ComponentError,
    EvidenceReference,
    Experiment,
    Proposal,
    RepositorySnapshot,
    RunMeasurement,
    SharedGoal,
    SuccessContract,
    VerdictRecord,
)


class RepositoryReader(Protocol):
    def read_snapshot(self, repository_id: str) -> RepositorySnapshot: ...


class GoalPlanner(Protocol):
    def define_contract(
        self, goal: SharedGoal, snapshot: RepositorySnapshot
    ) -> SuccessContract: ...


class ChangeProposer(Protocol):
    def propose(
        self,
        goal: SharedGoal,
        contract: SuccessContract,
        experiment: Experiment,
        snapshot: RepositorySnapshot,
    ) -> Proposal: ...


class PatchValidator(Protocol):
    def validate(
        self, proposal: Proposal, contract: SuccessContract, snapshot: RepositorySnapshot
    ) -> tuple[bool, tuple[ComponentError, ...]]: ...


class WorkflowExecutor(Protocol):
    def execute_pair(
        self, experiment: Experiment, proposal: Proposal, pair_index: int
    ) -> tuple[RunMeasurement, RunMeasurement]: ...


class ExperimentEvaluator(Protocol):
    def evaluate(self, experiment: Experiment, contract: SuccessContract) -> VerdictRecord: ...


class IndependentVerifier(Protocol):
    def verify(
        self,
        experiment: Experiment,
        contract: SuccessContract,
        verdict: VerdictRecord,
        evidence: tuple[EvidenceReference, ...],
    ) -> VerdictRecord: ...


class ExperimentStore(Protocol):
    def save_goal(self, goal: SharedGoal) -> None: ...
    def save_contract(self, contract: SuccessContract) -> None: ...
    def save_experiment(self, experiment: Experiment) -> None: ...
    def save_event(self, event_key: str, experiment_id: str, state: str, reason: str) -> None: ...
