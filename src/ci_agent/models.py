"""Shared, validated data contracts for CI snapshots and improvement experiments.

These records are the event-built extension around Shadow Runner's repository,
workflow, run, and job snapshot concepts. They are deliberately independent of
GitHub API payloads so adapters can translate external data at the boundary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def new_id() -> str:
    """Return a stable-format ID suitable for persisted records."""
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class ContractModel(BaseModel):
    """Base for immutable, versioned JSON-compatible records."""

    model_config = ConfigDict(frozen=True, extra="forbid", ser_json_timedelta="iso8601")
    schema_version: int = Field(default=1, ge=1)


class Verdict(StrEnum):
    WIN = "win"
    LOSS = "loss"
    VOID = "void"
    INCONCLUSIVE = "inconclusive"


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    CONTRACT_REVIEW = "contract_review"
    PROPOSED = "proposed"
    VALIDATING = "validating"
    RUNNING = "running"
    EVALUATING = "evaluating"
    WON = "won"
    LOST = "lost"
    VOID = "void"
    INCONCLUSIVE = "inconclusive"
    STOPPED = "stopped"


class RunVariant(StrEnum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"


class EvidenceKind(StrEnum):
    WORKFLOW = "workflow"
    DIFF = "diff"
    GITHUB_RUN = "github_run"
    JOB_LOG = "job_log"
    MEASUREMENT = "measurement"
    CONTRACT = "contract"
    REPORT = "report"
    OTHER = "other"


class JobSnapshot(ContractModel):
    id: str
    name: str
    status: str
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)


class RunSnapshot(ContractModel):
    id: str = Field(default_factory=new_id)
    repository_id: str
    workflow_id: str
    github_run_id: str
    attempt: int = Field(default=1, ge=1)
    source_revision: str
    status: str
    conclusion: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    origin_experiment_id: str | None = None
    is_fixture: bool = False
    jobs: tuple[JobSnapshot, ...] = ()

    @model_validator(mode="after")
    def completion_not_before_start(self) -> RunSnapshot:
        if self.started_at and self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at must be at or after started_at")
        return self


class WorkflowSnapshot(ContractModel):
    id: str
    repository_id: str
    path: str
    content_fingerprint: str
    raw_yaml: str | None = None


class RepositorySnapshot(ContractModel):
    id: str
    github_repository_id: str
    owner: str
    name: str
    default_branch: str
    workflows: tuple[WorkflowSnapshot, ...] = ()
    observed_runs: tuple[RunSnapshot, ...] = ()


class RequiredCheck(ContractModel):
    name: str
    command: str | None = None
    required: bool = True


class SuccessContract(ContractModel):
    """Immutable rules, approved before an experiment starts."""

    id: str = Field(default_factory=new_id)
    goal_id: str
    version: int = Field(ge=1)
    objective: str = "Reduce CI workflow completion time while preserving required checks."
    allowed_optimizations: tuple[str, ...] = ("caching", "parallelism")
    required_checks: tuple[RequiredCheck, ...]
    # User wait time from first required job start through last required job completion.
    metric: str = "required_jobs_wall_clock_seconds"
    minimum_samples: int = Field(default=3, ge=2)
    minimum_gain_percent: float = Field(default=5.0, ge=0)
    max_run_pairs: int = Field(default=3, ge=1)
    report_all_measured_effects: bool = True
    reviewed: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_checks_and_samples(self) -> SuccessContract:
        if not self.required_checks:
            raise ValueError("at least one required check must be specified")
        if self.minimum_samples != self.max_run_pairs:
            raise ValueError("first-version policy requires exactly minimum_samples run pairs")
        return self


class SharedGoal(ContractModel):
    """Long-lived objective shared across all experiments for a workflow."""

    id: str = Field(default_factory=new_id)
    workflow_id: str
    objective: str = "Make CI faster while preserving all required checks."
    constraints: tuple[str, ...] = ()
    active_contract_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Proposal(ContractModel):
    id: str = Field(default_factory=new_id)
    experiment_id: str
    hypothesis: str
    optimization_type: str
    patch: str
    patch_fingerprint: str = ""
    expected_effect: str
    affected_paths: tuple[str, ...]
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def fingerprint_patch(self) -> Proposal:
        digest = sha256(self.patch.encode("utf-8")).hexdigest()
        if self.patch_fingerprint and self.patch_fingerprint != digest:
            raise ValueError("patch_fingerprint does not match patch content")
        object.__setattr__(self, "patch_fingerprint", digest)
        return self


class RunMeasurement(ContractModel):
    id: str = Field(default_factory=new_id)
    experiment_id: str
    variant: RunVariant
    pair_index: int = Field(ge=1)
    run: RunSnapshot
    # Main metric: first required-job start to last required-job completion.
    wall_clock_seconds: float = Field(ge=0)
    # Secondary diagnostic: sum of required-job durations, not the main verdict metric.
    runner_seconds: float = Field(ge=0)
    queue_seconds: float = Field(default=0, ge=0)
    runner: str
    required_checks_passed: bool
    measured_at: datetime = Field(default_factory=utc_now)
    is_fixture: bool = False

    @model_validator(mode="after")
    def fixture_marker_consistent(self) -> RunMeasurement:
        if self.is_fixture != self.run.is_fixture:
            raise ValueError("measurement and run must agree on is_fixture")
        return self


class RunPair(ContractModel):
    id: str = Field(default_factory=new_id)
    experiment_id: str
    pair_index: int = Field(ge=1)
    baseline: RunMeasurement
    candidate: RunMeasurement

    @model_validator(mode="after")
    def matching_pair(self) -> RunPair:
        if self.baseline.variant != RunVariant.BASELINE:
            raise ValueError("baseline measurement must have baseline variant")
        if self.candidate.variant != RunVariant.CANDIDATE:
            raise ValueError("candidate measurement must have candidate variant")
        if (
            self.baseline.pair_index != self.pair_index
            or self.candidate.pair_index != self.pair_index
        ):
            raise ValueError("both measurements must use the run pair index")
        if (
            self.baseline.experiment_id != self.experiment_id
            or self.candidate.experiment_id != self.experiment_id
        ):
            raise ValueError("both measurements must belong to this experiment")
        if self.baseline.is_fixture != self.candidate.is_fixture:
            raise ValueError("cannot compare a fixture run with a real run")
        if self.baseline.runner != self.candidate.runner:
            raise ValueError("matched run pair must use the same runner")
        return self


class Experiment(ContractModel):
    id: str = Field(default_factory=new_id)
    goal_id: str
    contract_id: str
    repository_id: str
    workflow_id: str
    source_revision: str
    workflow_fingerprint: str
    comparison_key: str
    status: ExperimentStatus = ExperimentStatus.DRAFT
    trigger_run_id: str | None = None
    proposal_id: str | None = None
    parent_experiment_id: str | None = None
    run_pairs: tuple[RunPair, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)
    stop_reason: str | None = None
    hypothesis: str

    @model_validator(mode="after")
    def validate_experiment(self) -> Experiment:
        if any(pair.experiment_id != self.id for pair in self.run_pairs):
            raise ValueError("all run pairs must belong to this experiment")
        if len(self.run_pairs) != len({pair.pair_index for pair in self.run_pairs}):
            raise ValueError("run pair indexes must be unique within an experiment")
        return self


class VerdictRecord(ContractModel):
    id: str = Field(default_factory=new_id)
    experiment_id: str
    contract_id: str
    outcome: Verdict
    evidence_fingerprint: str
    method_version: str
    sample_count: int = Field(ge=0)
    metric: str = "required_jobs_wall_clock_seconds"
    baseline_mean_wall_clock_seconds: float | None = Field(default=None, ge=0)
    candidate_mean_wall_clock_seconds: float | None = Field(default=None, ge=0)
    wall_clock_saved_seconds: float | None = None
    runner_seconds_saved: float | None = None
    queue_seconds_saved: float | None = None
    uncertainty_low_wall_clock_seconds: float | None = None
    uncertainty_high_wall_clock_seconds: float | None = None
    reported_effects: tuple[str, ...] = ()
    checks_passed: tuple[str, ...] = ()
    checks_failed: tuple[str, ...] = ()
    explanation: str
    created_at: datetime = Field(default_factory=utc_now)


class ExperimentEvent(ContractModel):
    id: str = Field(default_factory=new_id)
    experiment_id: str
    event_key: str
    state: ExperimentStatus
    reason: str
    occurred_at: datetime = Field(default_factory=utc_now)
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceReference(ContractModel):
    id: str = Field(default_factory=new_id)
    experiment_id: str
    kind: EvidenceKind
    uri: str
    fingerprint: str
    is_fixture: bool = False
    captured_at: datetime = Field(default_factory=utc_now)


class ComponentError(ContractModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


def fingerprint_json(value: Any) -> str:
    """Hash canonical JSON for duplicate and evidence comparisons."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()
