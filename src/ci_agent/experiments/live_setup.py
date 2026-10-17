"""Pin current source, generate a reviewed contract and independently reviewed proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dotenv import load_dotenv

from ci_agent.contracts import ContractRequest, generate_contract, load_contract, save_contract
from ci_agent.experiments.live_proposal import (
    LiveProposal,
    ProposalReview,
    generate_live_proposal,
)
from ci_agent.github.fork_experiment import _content_text
from ci_agent.github.runs import GitHubClient
from ci_agent.inference import CrusoeInference, InferenceError


class BoundedStructuredClient:
    """Retry malformed model JSON without weakening model or local validation."""

    def __init__(self, client):
        self.client = client

    def complete_structured(self, **kwargs):
        for attempt in range(3):
            try:
                return self.client.complete_structured(**kwargs)
            except InferenceError as exc:
                if 'structured output schema' not in str(exc) or attempt == 2:
                    raise
                print('Model returned invalid structured output; retrying bounded call.', flush=True)


def prepare_e2e(*, repository: str, output: Path, template: Path, resume: bool = False):
    if output.exists():
        if not resume:
            raise FileExistsError('Setup output already exists; explicitly resume it')
        return _resume_e2e(repository=repository, output=output)
    output.mkdir(parents=True, exist_ok=False)
    load_dotenv()
    github = GitHubClient.from_git_credential()
    client = BoundedStructuredClient(CrusoeInference.from_env(timeout_seconds=180))
    owner, name = repository.split('/')
    branch, sha = github.default_branch(owner, name)
    payload = json.loads(template.read_text(encoding='utf-8'))
    path = payload['context']['workflow']['path']
    baseline = _content_text(github.get_contents(owner, name, path, sha))
    payload['context']['repository'] = repository
    payload['context']['workflow'].update(
        repository_id=repository.replace('/', '-'), raw_yaml=baseline,
        content_fingerprint=hashlib.sha256(baseline.encode()).hexdigest(),
    )
    from ci_agent.strategies import REGISTRY
    payload['limits']['allowed_optimizations'] = list(REGISTRY)
    request = ContractRequest.model_validate(payload)
    (output / 'contract-request.json').write_text(request.model_dump_json(indent=2) + '\n', encoding='utf-8')
    (output / 'source.json').write_text(json.dumps({
        'repository': repository, 'branch': branch, 'sha': sha, 'workflow_path': path,
    }, indent=2) + '\n', encoding='utf-8')
    (output / 'baseline.yml').write_text(baseline, encoding='utf-8')
    print(f'Pinned {repository}@{sha}; requesting live contract generation and review.', flush=True)
    result = generate_contract(request.goal, request.context, request.limits, client)
    (output / 'contract-generation.json').write_text(result.model_dump_json(indent=2) + '\n', encoding='utf-8')
    if result.status != 'ready':
        raise ValueError(f'Contract generation did not approve: {result.status}; inspect saved result')
    save_contract(output / 'contract' / 'success-contract.json', result.sealed_contract)
    print('Reviewed contract saved; requesting live proposal and independent review.', flush=True)
    generate_live_proposal(
        client, repository=repository, baseline=baseline,
        sealed_contract=result.sealed_contract, output=output / 'proposal',
        evidence=(
            f'Workflow source is pinned to {sha}.',
            'No measured optimization savings are available.',
        ),
    )
    print(f'Reviewed candidate saved to {output / "proposal" / "candidate.yml"}', flush=True)

    return {'repository': repository, 'branch': branch, 'sha': sha, 'workflow_path': path}


def _resume_e2e(*, repository: str, output: Path):
    """Trust only locally validated records; never overwrite completed model evidence."""
    source = json.loads((output / 'source.json').read_text(encoding='utf-8'))
    request = ContractRequest.model_validate_json(
        (output / 'contract-request.json').read_text(encoding='utf-8')
    )
    baseline = (output / 'baseline.yml').read_text(encoding='utf-8')
    workflow = request.context.workflow
    fingerprint = hashlib.sha256(baseline.encode()).hexdigest()
    if (
        source.get('repository') != repository or request.context.repository != repository
        or not source.get('sha') or source.get('workflow_path') != workflow.path
        or workflow.raw_yaml != baseline or workflow.content_fingerprint != fingerprint
    ):
        raise ValueError('Saved setup source, repository, or workflow fingerprint is inconsistent')
    contract_path = output / 'contract' / 'success-contract.json'
    sealed = load_contract(contract_path) if contract_path.exists() else None
    if sealed is not None and (
        sealed.contract.goal_id != request.goal.id
        or sealed.contract.objective != request.goal.objective
        or sealed.contract.version != request.context.version
        or sealed.contract.required_checks != request.context.required_checks
        or any(
            getattr(sealed.contract, field) != getattr(request.limits, field)
            for field in type(request.limits).model_fields
        )
    ):
        raise ValueError('Saved contract does not match the pinned setup request')
    proposal_path = output / 'proposal' / 'proposal.json'
    candidate_path = output / 'proposal' / 'candidate.yml'
    if candidate_path.exists():
        if sealed is None:
            raise ValueError('A saved candidate requires a sealed contract')
        audit = json.loads(proposal_path.read_text(encoding='utf-8'))
        proposal = LiveProposal.model_validate(audit['proposal'])
        review = ProposalReview.model_validate(audit['review'])
        candidate = candidate_path.read_text(encoding='utf-8')
        if (
            not review.approved or review.issues or candidate != proposal.candidate_workflow
            or audit.get('baseline_sha256') != fingerprint
            or audit.get('contract_fingerprint') != sealed.contract_fingerprint
            or audit.get('proposer_context', {}).get('repository') != repository
        ):
            raise ValueError('Saved proposal or independent review is inconsistent')
        from ci_agent.strategies import validate_strategy
        if proposal.optimization not in sealed.contract.allowed_optimizations:
            raise ValueError('Saved strategy is outside contract')
        validate_strategy(proposal.optimization, baseline, candidate)
        return source
    if (output / 'proposal').exists():
        raise ValueError('Incomplete or rejected proposal records must be inspected before retrying')
    load_dotenv()
    client = BoundedStructuredClient(CrusoeInference.from_env(timeout_seconds=180))
    if sealed is None:
        if (output / 'contract-generation.json').exists():
            raise ValueError('Existing contract generation records require inspection before retrying')
        result = generate_contract(request.goal, request.context, request.limits, client)
        (output / 'contract-generation.json').write_text(
            result.model_dump_json(indent=2) + '\n', encoding='utf-8'
        )
        if result.status != 'ready':
            raise ValueError('Resumed contract generation was not approved')
        sealed = result.sealed_contract
        save_contract(contract_path, sealed)
    generate_live_proposal(
        client, repository=repository, baseline=baseline, sealed_contract=sealed,
        output=output / 'proposal',
        evidence=(f'Workflow source is pinned to {source["sha"]}.',),
    )
    return source
