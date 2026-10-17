"""Generate, independently review, lock, and persist experiment success rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ci_agent.models import (
    RequiredCheck,
    SharedGoal,
    SuccessContract,
    WorkflowSnapshot,
    fingerprint_json,
)

GENERATOR_PROMPT_VERSION = "contract-generator-v1"
REVIEWER_PROMPT_VERSION = "contract-reviewer-v1"


class StructuredInference(Protocol):
    def complete_structured(
        self, *, system_prompt: str, user_prompt: str, output_model: type[BaseModel]
    ) -> BaseModel: ...


DEFAULT_COMPARISON_CONDITIONS = (
    "Run baseline and candidate on the same workflow revision.",
    "Use the same runner type and dependency/cache conditions for each pair.",
    "Run the full required workflow matrix; do not omit required matrix cells.",
    "Aggregate required_runner_minutes by summing runner minutes across all required jobs and matrix cells.",
    "The experiment time cap measures elapsed wall-clock time, not summed runner minutes.",
    "Keep queue delay separate from runner time.",
)
DEFAULT_STOP_CONDITIONS = (
    "Stop if any required check is disabled, removed, or fails.",
    "Stop when the configured attempt, run-pair, or time budget is exhausted.",
    "Stop and request human input when required context or access is missing.",
)
PRACTICAL_WIN_RULE = (
    "A practical win requires all three matched pairs to reduce required runner minutes and "
    "the mean reduction to be at least 5%. This is a project decision rule, not proof of statistical certainty."
)
CONFIDENCE_INTERVAL_RULE = (
    "Report a paired 95% confidence interval for the mean runner-minute reduction alongside all three "
    "pair results. Treat it as exploratory with only three pairs; it does not determine the practical "
    "win verdict and must not be described as proof of statistical certainty."
)


class ContractContext(BaseModel):
    """Repository/workflow facts and explicitly enumerated required checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str = Field(min_length=3)
    workflow: WorkflowSnapshot
    required_checks: tuple[RequiredCheck, ...]
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def required_checks_are_unambiguous(self) -> ContractContext:
        if not self.required_checks:
            raise ValueError("context must enumerate the workflow's required checks")
        names = [check.name for check in self.required_checks]
        if len(names) != len(set(names)):
            raise ValueError("required check names must be unique")
        if any(not check.required for check in self.required_checks):
            raise ValueError("context checks must all be marked required")
        return self


class ContractLimits(BaseModel):
    """Locked project policy and bounded resources supplied to the planner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_optimizations: tuple[str, ...] = (
        "caching", "parallelism", "checkout_reduction", "setup_removal",
        "superseded_cancellation", "service_readiness",
    )
    metric: str = "required_runner_minutes"
    is_first_improvement: bool = True
    minimum_gain_percent: float = Field(default=5.0, ge=0)
    practical_win_rule: str = PRACTICAL_WIN_RULE
    minimum_samples: int = Field(default=3, ge=2)
    max_run_pairs: int = Field(default=3, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    max_experiment_minutes: int = Field(default=1440, ge=1)
    highlight_below_percent: float = Field(default=1.0, ge=0)
    uncertainty_method: str | None = None
    confidence_interval_method: str = CONFIDENCE_INTERVAL_RULE
    comparison_conditions: tuple[str, ...] = DEFAULT_COMPARISON_CONDITIONS
    stop_conditions: tuple[str, ...] = DEFAULT_STOP_CONDITIONS

    @model_validator(mode="after")
    def validate_locked_policy(self) -> ContractLimits:
        if not self.allowed_optimizations:
            raise ValueError("at least one allowed optimization must be configured")
        if self.minimum_samples != self.max_run_pairs:
            raise ValueError("minimum_samples and max_run_pairs must match")
        expected_gain = 5.0 if self.is_first_improvement else 0.0
        if self.minimum_gain_percent != expected_gain:
            raise ValueError("the first improvement requires 5%; later improvements require positive gain")
        if not self.comparison_conditions or not self.stop_conditions:
            raise ValueError("comparison and stop conditions must be explicit")
        if self.practical_win_rule != PRACTICAL_WIN_RULE:
            raise ValueError("the practical win rule is locked by project policy")
        if self.confidence_interval_method != CONFIDENCE_INTERVAL_RULE:
            raise ValueError("the confidence interval reporting rule is locked by project policy")
        if self.uncertainty_method is not None and not self.uncertainty_method.strip():
            raise ValueError("uncertainty_method must be a meaningful description or omitted")
        return self


class ContractRules(BaseModel):
    """Structured rules proposed by the Planner; checked against locked limits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    objective: str
    allowed_optimizations: tuple[str, ...]
    required_checks: tuple[RequiredCheck, ...]
    metric: str
    is_first_improvement: bool
    minimum_gain_percent: float = Field(ge=0)
    practical_win_rule: str
    minimum_samples: int = Field(ge=2)
    max_run_pairs: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    max_experiment_minutes: int = Field(ge=1)
    highlight_below_percent: float = Field(ge=0)
    uncertainty_method: str
    confidence_interval_method: str
    comparison_conditions: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    report_all_measured_effects: bool = True


class ContractReview(BaseModel):
    """Independent Verifier result; never sufficient to bypass local rule checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approved: bool
    missing_rules: tuple[str, ...] = ()
    unsafe_rules: tuple[str, ...] = ()
    infeasible_rules: tuple[str, ...] = ()
    rationale: str
    human_question: str | None = None


class SealedContract(BaseModel):
    """A reviewed contract paired with a canonical fingerprint for tamper checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract: SuccessContract
    contract_fingerprint: str
    review: ContractReview
    generator_prompt_version: str = GENERATOR_PROMPT_VERSION
    reviewer_prompt_version: str = REVIEWER_PROMPT_VERSION

    @model_validator(mode="after")
    def seal_is_valid_and_reviewed(self) -> SealedContract:
        if not self.contract.reviewed:
            raise ValueError("only a reviewed contract can be sealed")
        if contract_fingerprint(self.contract) != self.contract_fingerprint:
            raise ValueError("contract fingerprint does not match its rules")
        if not self.review.approved:
            raise ValueError("only an approved contract can be sealed")
        return self


class ContractGenerationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ready", "needs_human", "rejected"]
    sealed_contract: SealedContract | None = None
    reasons: tuple[str, ...] = ()
    human_question: str | None = None

    @model_validator(mode="after")
    def status_payload_is_consistent(self) -> ContractGenerationResult:
        if self.status == "ready" and self.sealed_contract is None:
            raise ValueError("ready results require a sealed contract")
        if self.status != "ready" and self.sealed_contract is not None:
            raise ValueError("non-ready results cannot contain a sealed contract")
        if self.status == "needs_human" and not self.human_question:
            raise ValueError("needs_human results require a specific question")
        if self.status == "rejected" and not self.reasons:
            raise ValueError("rejected results require reasons")
        return self


class ContractRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: SharedGoal
    context: ContractContext
    limits: ContractLimits = Field(default_factory=ContractLimits)


def contract_fingerprint(contract: SuccessContract) -> str:
    """Fingerprint the immutable grading rules, excluding review metadata."""
    rules = contract.model_dump(mode="json", exclude={"id", "created_at", "reviewed"})
    return fingerprint_json(rules)


def _policy_mismatches(
    goal: SharedGoal, context: ContractContext, limits: ContractLimits, rules: ContractRules
) -> tuple[str, ...]:
    reasons: list[str] = []
    expected_checks = sorted(
        (check.model_dump(mode="json") for check in context.required_checks), key=lambda item: item["name"]
    )
    actual_checks = sorted(
        (check.model_dump(mode="json") for check in rules.required_checks), key=lambda item: item["name"]
    )
    if actual_checks != expected_checks:
        reasons.append("The required checks do not exactly match the checks supplied by the workflow owner.")
    if rules.objective != goal.objective:
        reasons.append("The objective changed from the saved goal.")
    if not rules.allowed_optimizations or not set(rules.allowed_optimizations) <= set(limits.allowed_optimizations):
        reasons.append("The draft includes an optimization outside the approved set.")
    if rules.metric != limits.metric:
        reasons.append("The primary metric differs from the locked project metric.")
    locked_fields = (
        "is_first_improvement", "minimum_gain_percent", "practical_win_rule", "minimum_samples", "max_run_pairs",
        "max_attempts", "max_experiment_minutes", "highlight_below_percent",
        "uncertainty_method", "confidence_interval_method", "comparison_conditions", "stop_conditions",
        "report_all_measured_effects",
    )
    for field in locked_fields:
        expected = getattr(limits, field, True)
        actual = getattr(rules, field)
        if field in {"comparison_conditions", "stop_conditions"}:
            if set(actual) != set(expected):
                reasons.append(f"The {field.replace('_', ' ')} do not match the locked plan.")
        elif actual != expected:
            reasons.append(f"The {field.replace('_', ' ')} differs from the locked plan.")
    if not rules.uncertainty_method.strip():
        reasons.append("An uncertainty method must be written into the contract before testing.")
    return tuple(reasons)


def _as_success_contract(goal: SharedGoal, context: ContractContext, rules: ContractRules) -> SuccessContract:
    return SuccessContract(
        goal_id=goal.id,
        version=context.version,
        objective=rules.objective,
        allowed_optimizations=rules.allowed_optimizations,
        required_checks=rules.required_checks,
        metric=rules.metric,
        minimum_samples=rules.minimum_samples,
        is_first_improvement=rules.is_first_improvement,
        minimum_gain_percent=rules.minimum_gain_percent,
        practical_win_rule=rules.practical_win_rule,
        highlight_below_percent=rules.highlight_below_percent,
        max_run_pairs=rules.max_run_pairs,
        max_attempts=rules.max_attempts,
        max_experiment_minutes=rules.max_experiment_minutes,
        comparison_conditions=rules.comparison_conditions,
        uncertainty_method=rules.uncertainty_method,
        confidence_interval_method=rules.confidence_interval_method,
        stop_conditions=rules.stop_conditions,
        report_all_measured_effects=rules.report_all_measured_effects,
        reviewed=False,
    )


def review_contract(
    contract: SuccessContract,
    *,
    goal: SharedGoal,
    context: ContractContext,
    limits: ContractLimits,
    client: StructuredInference,
) -> ContractReview:
    """Ask the separate Verifier role to review completeness and feasibility."""
    review = client.complete_structured(
        system_prompt=(
            "You are the independent Contract Verifier. Review the proposed rules against the goal, "
            "workflow evidence, and locked limits. Do not rewrite or loosen rules. Check that every "
            "required check remains enabled and passing, the metric and improvement rule are explicit, "
            "matched-run conditions are fair, and stop limits are actionable. List every issue; "
            "ask one specific question if a material ambiguity remains. Return only the requested schema."
        ),
        user_prompt=json.dumps({
            "goal": goal.model_dump(mode="json"),
            "repository": context.repository,
            "workflow": context.workflow.model_dump(mode="json"),
            "required_checks": [check.model_dump(mode="json") for check in context.required_checks],
            "locked_limits": limits.model_dump(mode="json"),
            "contract": contract.model_dump(mode="json"),
        }, sort_keys=True),
        output_model=ContractReview,
    )
    if not isinstance(review, ContractReview):
        review = ContractReview.model_validate(review)
    return review


def generate_contract(
    goal: SharedGoal,
    context: ContractContext,
    limits: ContractLimits,
    client: StructuredInference | None,
) -> ContractGenerationResult:
    """Generate rules, enforce locked policy, run independent review, and seal."""
    if not limits.uncertainty_method:
        return ContractGenerationResult(
            status="needs_human",
            human_question=(
                "The project has fixed its practical win rule (all three pairs improve and mean reduction "
                "is at least 5%) and its exploratory paired 95% confidence-interval reporting rule. "
                "What uncertainty method should be recorded for interpreting/reporting the interval? "
                "This must be fixed before collecting comparison runs."
            ),
        )
    if client is None:
        raise ValueError("a configured Crusoe client is required when generating a complete contract")

    rules = client.complete_structured(
        system_prompt=(
            "You are the Contract Planner. Turn the saved goal and workflow facts into a complete "
            "machine-checkable experiment contract. Preserve every supplied required check and every "
            "locked limit exactly. Do not invent tests or change thresholds. State fair comparison and "
            "stop conditions plainly. If facts are missing, return the closest faithful rules; the "
            "independent reviewer will reject gaps. Return only the requested schema."
        ),
        user_prompt=json.dumps({
            "goal": goal.model_dump(mode="json"),
            "repository": context.repository,
            "workflow": context.workflow.model_dump(mode="json"),
            "required_checks": [check.model_dump(mode="json") for check in context.required_checks],
            "locked_limits": limits.model_dump(mode="json"),
        }, sort_keys=True),
        output_model=ContractRules,
    )
    if not isinstance(rules, ContractRules):
        try:
            rules = ContractRules.model_validate(rules)
        except ValidationError as exc:
            return ContractGenerationResult(status="rejected", reasons=(str(exc),))

    mismatches = _policy_mismatches(goal, context, limits, rules)
    if mismatches:
        return ContractGenerationResult(status="rejected", reasons=mismatches)

    contract = _as_success_contract(goal, context, rules)
    review = review_contract(contract, goal=goal, context=context, limits=limits, client=client)
    review_issues = (*review.missing_rules, *review.unsafe_rules, *review.infeasible_rules)
    if not review.approved or review_issues or review.human_question:
        return ContractGenerationResult(
            status="rejected",
            reasons=(review.rationale, *review_issues),
            human_question=review.human_question,
        )

    reviewed_contract = SuccessContract.model_validate(
        contract.model_dump(mode="python") | {"reviewed": True}
    )
    sealed = SealedContract(
        contract=reviewed_contract,
        contract_fingerprint=contract_fingerprint(reviewed_contract),
        review=review,
    )
    return ContractGenerationResult(status="ready", sealed_contract=sealed)


def save_contract(path: Path, sealed: SealedContract) -> None:
    """Persist an already reviewed contract before any proposal is created."""
    # Re-validate on save so serialized/tampered objects cannot bypass the seal.
    SealedContract.model_validate(sealed.model_dump(mode="python"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sealed.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_contract(path: Path) -> SealedContract:
    """Load and verify the saved rules before an experiment uses them."""
    return SealedContract.model_validate_json(path.read_text(encoding="utf-8"))
