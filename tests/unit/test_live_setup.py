import hashlib
import json
from pathlib import Path

import pytest

from ci_agent.contracts import (
    ContractRequest,
    ContractReview,
    SealedContract,
    contract_fingerprint,
    save_contract,
)
from ci_agent.experiments.live_setup import prepare_e2e
from ci_agent.models import SuccessContract


@pytest.fixture
def completed_setup(tmp_path):
    template = Path('config/contract-request.example.json')
    payload = json.loads(template.read_text())
    payload['limits']['allowed_optimizations'] = ['service_readiness']
    request = ContractRequest.model_validate(payload)
    baseline = request.context.workflow.raw_yaml
    candidate = baseline.replace('--health-interval 10s', '--health-interval 1s').replace(
        '--health-retries 5', '--health-retries 50'
    )
    contract = SuccessContract(
        goal_id=request.goal.id, version=1, objective=request.goal.objective,
        required_checks=request.context.required_checks,
        allowed_optimizations=request.limits.allowed_optimizations, reviewed=True,
        uncertainty_method=request.limits.uncertainty_method,
    )
    sealed = SealedContract(
        contract=contract, contract_fingerprint=contract_fingerprint(contract),
        review=ContractReview(approved=True, rationale='Complete'),
    )
    source = {'repository': request.context.repository, 'sha': 'abc', 'branch': 'master',
                  'workflow_path': request.context.workflow.path}
    (tmp_path / 'source.json').write_text(json.dumps(source))
    (tmp_path / 'baseline.yml').write_text(baseline)
    (tmp_path / 'contract-request.json').write_text(request.model_dump_json())
    save_contract(tmp_path / 'contract' / 'success-contract.json', sealed)
    proposal = tmp_path / 'proposal'
    proposal.mkdir()
    (proposal / 'candidate.yml').write_text(candidate)
    (proposal / 'proposal.json').write_text(json.dumps({
        'baseline_sha256': hashlib.sha256(baseline.encode()).hexdigest(),
        'contract_fingerprint': sealed.contract_fingerprint,
        'proposer_context': {'repository': request.context.repository},
        'proposal': {'optimization': 'service_readiness', 'candidate_workflow': candidate,
                         'hypothesis': 'May reduce polling idle time', 'evidence': ['Workflow'], 'risks': []},
        'review': {'approved': True, 'issues': [], 'rationale': 'Preserves checks'},
    }))
    return tmp_path, source


def test_completed_resume_uses_no_network_or_inference(completed_setup, monkeypatch):
    output, source = completed_setup

    def unexpected(*args, **kwargs):
        raise AssertionError('Completed setup must not call external services')

    monkeypatch.setattr('ci_agent.experiments.live_setup.GitHubClient.from_git_credential', unexpected)
    monkeypatch.setattr('ci_agent.experiments.live_setup.CrusoeInference.from_env', unexpected)
    assert prepare_e2e(repository=source['repository'], output=output,
                       template=Path('missing'), resume=True) == source


def test_resume_rejects_changed_baseline(completed_setup):
    output, source = completed_setup
    (output / 'baseline.yml').write_text('jobs: {}')
    with pytest.raises(ValueError, match='fingerprint'):
        prepare_e2e(repository=source['repository'], output=output,
                    template=Path('missing'), resume=True)


def test_resume_requires_explicit_flag(completed_setup):
    output, source = completed_setup
    with pytest.raises(FileExistsError):
        prepare_e2e(repository=source['repository'], output=output, template=Path('missing'))
