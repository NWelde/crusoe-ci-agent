import pytest
import yaml

from ci_agent.contracts import ContractReview, SealedContract, contract_fingerprint
from ci_agent.experiments.live_proposal import (
    LiveProposal,
    ProposalReview,
    generate_live_proposal,
    validate_service_polling,
)
from ci_agent.models import RequiredCheck, SuccessContract

BASELINE = """
name: CI
on: [push]
jobs:
  tests:
    runs-on: ubuntu-24.04
    strategy:
      matrix:
        ruby: ['3.2', '3.3']
    services:
      db:
        image: postgres:17
        options: --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
    steps:
      - run: bundle exec rake spec
"""
CANDIDATE = BASELINE.replace('--health-interval 10s', '--health-interval 1s').replace(
    '--health-retries 5', '--health-retries 50'
)


def test_accepts_only_faster_polling_with_preserved_budget():
    validate_service_polling(BASELINE, CANDIDATE)


@pytest.mark.parametrize('candidate', [
    BASELINE,
    CANDIDATE.replace('--health-timeout 5s', '--health-timeout 1s'),
    CANDIDATE.replace('--health-retries 50', '--health-retries 5'),
    CANDIDATE.replace('bundle exec rake spec', 'true'),
    CANDIDATE.replace("['3.2', '3.3']", "['3.2']"),
    CANDIDATE.replace('postgres:17', 'postgres:18'),
    CANDIDATE.replace('pg_isready', 'true'),
    CANDIDATE.replace('on: [push]', 'on: [workflow_dispatch]'),
    CANDIDATE.replace('runs-on: ubuntu-24.04', 'runs-on: ubuntu-latest'),
])
def test_rejects_changes_to_checks_matrix_database_and_triggers(candidate):
    with pytest.raises(ValueError):
        validate_service_polling(BASELINE, candidate)


def test_rejects_extra_jobs():
    parsed = yaml.safe_load(CANDIDATE)
    parsed['jobs']['extra'] = {'steps': [{'run': 'echo extra'}]}
    with pytest.raises(ValueError):
        validate_service_polling(BASELINE, yaml.safe_dump(parsed))


def test_independent_rejection_saves_review_but_no_executable_candidate(tmp_path):
    contract = SuccessContract(
        goal_id='goal', version=1, required_checks=(RequiredCheck(name='tests'),),
        allowed_optimizations=('service_readiness',), reviewed=True,
        uncertainty_method='Exploratory paired t interval',
    )
    sealed = SealedContract(
        contract=contract, contract_fingerprint=contract_fingerprint(contract),
        review=ContractReview(approved=True, rationale='Complete'),
    )

    class Client:
        def __init__(self):
            self.calls = []

        def complete_structured(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs['output_model'] is LiveProposal:
                return LiveProposal(
                    optimization='service_readiness', candidate_workflow=CANDIDATE,
                    hypothesis='Shorter readiness idle polling may reduce job runtime.',
                    evidence=('Workflow has a 10 second interval.',), risks=('May not improve.',),
                )
            return ProposalReview(approved=False, issues=('Unsupported evidence',), rationale='Reject')

    client = Client()
    output = tmp_path / 'proposal'
    with pytest.raises(ValueError, match='Independent proposal review'):
        generate_live_proposal(
            client, repository='team/repo', baseline=BASELINE,
            sealed_contract=sealed, output=output,
        )
    assert len(client.calls) == 2
    assert client.calls[0]['system_prompt'] != client.calls[1]['system_prompt']
    assert (output / 'proposal.json').exists()
    assert not (output / 'candidate.yml').exists()
