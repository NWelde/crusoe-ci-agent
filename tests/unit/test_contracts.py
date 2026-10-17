import json

import pytest
from pydantic import ValidationError

from ci_agent.contracts import (
    ContractContext,
    ContractLimits,
    ContractReview,
    ContractRules,
    generate_contract,
    load_contract,
    save_contract,
)
from ci_agent.models import RequiredCheck, SharedGoal, SuccessContract, WorkflowSnapshot

UNCERTAINTY_METHOD = "paired t-based 95% confidence interval, exploratory with n=3; report alongside all pairs and never as proof of certainty"


def make_context():
    return ContractContext(
        repository="madeintandem/jsonb_accessor",
        workflow=WorkflowSnapshot(
            id="ci",
            repository_id="madeintandem-jsonb-accessor",
            path=".github/workflows/ci.yml",
            content_fingerprint="workflow-sha256",
        ),
        required_checks=(
            RequiredCheck(name="lint", command="bundle exec rubocop"),
            RequiredCheck(name="tests", command="bundle exec rake spec"),
        ),
    )


def make_rules(**overrides):
    fields = {
        "objective": "Reduce GitHub Actions runner minutes while keeping all required CI checks enabled and passing.",
        "allowed_optimizations": ("caching", "parallelism"),
        "required_checks": make_context().required_checks,
        "metric": "required_runner_minutes",
        "is_first_improvement": True,
        "minimum_gain_percent": 5.0,
        "practical_win_rule": ContractLimits().practical_win_rule,
        "minimum_samples": 3,
        "max_run_pairs": 3,
        "max_attempts": 3,
        "max_experiment_minutes": 1440,
        "highlight_below_percent": 1.0,
        "uncertainty_method": UNCERTAINTY_METHOD,
        "confidence_interval_method": ContractLimits().confidence_interval_method,
        "comparison_conditions": ContractLimits().comparison_conditions,
        "stop_conditions": ContractLimits().stop_conditions,
        "report_all_measured_effects": True,
    }
    fields.update(overrides)
    return ContractRules(**fields)


class FakeInference:
    def __init__(self, rules=None, review=None):
        self.rules = rules or make_rules()
        self.review = review or ContractReview(approved=True, rationale="Rules are complete and feasible.")
        self.calls = []

    def complete_structured(self, *, system_prompt, user_prompt, output_model):
        self.calls.append((system_prompt, json.loads(user_prompt), output_model))
        return self.rules if output_model is ContractRules else self.review


def make_goal():
    return SharedGoal(
        workflow_id="ci",
        objective="Reduce GitHub Actions runner minutes while keeping all required CI checks enabled and passing.",
    )


def test_missing_uncertainty_method_asks_a_specific_question_without_calling_model():
    client = FakeInference()
    result = generate_contract(make_goal(), make_context(), ContractLimits(), client)

    assert result.status == "needs_human"
    assert "What uncertainty method" in result.human_question
    assert client.calls == []
    assert "all three pairs improve" in result.human_question
    assert "confidence-interval reporting rule" in result.human_question


def test_contract_is_generated_reviewed_sealed_and_persisted(tmp_path):
    limits = ContractLimits(uncertainty_method=UNCERTAINTY_METHOD)
    client = FakeInference()
    result = generate_contract(make_goal(), make_context(), limits, client)

    assert result.status == "ready"
    sealed = result.sealed_contract
    assert sealed is not None
    assert sealed.contract.reviewed is True
    assert len(sealed.contract_fingerprint) == 64
    assert len(client.calls) == 2
    assert "Planner" in client.calls[0][0]
    assert "independent Contract Verifier" in client.calls[1][0]
    assert client.calls[0][2] is ContractRules
    assert client.calls[1][2] is ContractReview

    path = tmp_path / "contract.json"
    save_contract(path, sealed)
    assert load_contract(path) == sealed


def test_contract_change_invalidates_saved_fingerprint(tmp_path):
    client = FakeInference()
    limits = ContractLimits(uncertainty_method=UNCERTAINTY_METHOD)
    result = generate_contract(make_goal(), make_context(), limits, client)
    payload = json.loads(result.sealed_contract.model_dump_json())
    payload["contract"]["metric"] = "elapsed_seconds"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="fingerprint does not match"):
        load_contract(path)


def test_saved_contract_rules_are_immutable():
    client = FakeInference()
    result = generate_contract(
        make_goal(), make_context(), ContractLimits(uncertainty_method=UNCERTAINTY_METHOD), client
    )

    with pytest.raises(ValidationError, match="frozen"):
        result.sealed_contract.contract.minimum_gain_percent = 0


def test_planner_cannot_remove_a_required_check_or_change_threshold():
    invalid_rules = make_rules(
        required_checks=(RequiredCheck(name="lint", command="bundle exec rubocop"),),
        minimum_gain_percent=0,
    )
    client = FakeInference(rules=invalid_rules)

    result = generate_contract(
        make_goal(), make_context(), ContractLimits(uncertainty_method=UNCERTAINTY_METHOD), client
    )

    assert result.status == "rejected"
    assert any("required checks" in reason for reason in result.reasons)
    assert any("minimum gain" in reason for reason in result.reasons)
    assert len(client.calls) == 1  # The independent reviewer never sees an unsafe draft.


def test_planner_cannot_change_practical_win_or_confidence_interval_rule():
    client = FakeInference(rules=make_rules(
        practical_win_rule="Win if one pair improves.",
        confidence_interval_method="Use interval as proof of certainty.",
    ))
    result = generate_contract(
        make_goal(), make_context(), ContractLimits(uncertainty_method=UNCERTAINTY_METHOD), client
    )

    assert result.status == "rejected"
    assert any("practical win rule" in reason for reason in result.reasons)
    assert any("confidence interval method" in reason for reason in result.reasons)
    assert len(client.calls) == 1


def test_verifier_rejection_keeps_contract_unsealed():
    client = FakeInference(review=ContractReview(
        approved=False,
        missing_rules=("The test matrix is not fully enumerated.",),
        rationale="The run comparison cannot be reproduced yet.",
        human_question="Which Ruby, Rails, and PostgreSQL matrix combinations are mandatory?",
    ))

    result = generate_contract(
        make_goal(), make_context(), ContractLimits(uncertainty_method=UNCERTAINTY_METHOD), client
    )

    assert result.status == "rejected"
    assert result.sealed_contract is None
    assert result.human_question.startswith("Which Ruby")


def test_contract_requires_unique_required_checks():
    with pytest.raises(ValidationError, match="unique"):
        ContractContext(
            repository="example/project",
            workflow=make_context().workflow,
            required_checks=(RequiredCheck(name="tests"), RequiredCheck(name="tests")),
        )


def test_unreviewed_contract_cannot_be_sealed():
    contract = SuccessContract(
        goal_id="goal-1", version=1, required_checks=(RequiredCheck(name="tests"),)
    )
    assert contract.reviewed is False
