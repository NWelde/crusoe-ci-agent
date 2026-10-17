"""Qualify the complete repaired upstream baseline before optimization trials."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from ci_agent.github.fork_experiment import _content_text, prepare_fork_experiment
from ci_agent.github.runs import GitHubClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', default='madeintandem/jsonb_accessor')
    parser.add_argument('--fork', default='NWelde/jsonb_accessor')
    parser.add_argument('--source-sha', default='cef7a810a48ce9c3b8a79015591fddfb1a963e5a')
    parser.add_argument('--workflow', default='.github/workflows/ci.yml')
    parser.add_argument('--common-source-files', type=Path, default=Path('artifacts/e2e-jsonb/baseline-fixes.json'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/final-baseline-health'))
    args = parser.parse_args()
    client = GitHubClient.from_git_credential()
    owner, repo = args.upstream.split('/')
    workflow = _content_text(client.get_contents(owner, repo, args.workflow, args.source_sha))
    args.output.mkdir(parents=True, exist_ok=False)
    def save(name, data):
        (args.output / name).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    prepared = prepare_fork_experiment(
        client, args.upstream, args.workflow, workflow, run_key='final-health',
        source_sha=args.source_sha, existing_fork=args.fork,
        common_source_files=json.loads(args.common_source_files.read_text(encoding='utf-8')),
        on_progress=lambda progress: print(json.dumps(progress), flush=True),
    )
    save('prepared.json', asdict(prepared))
    started = datetime.now(UTC)
    client.dispatch_workflow(prepared.owner, prepared.name, prepared.workflow_id, prepared.baseline_branch)
    run = client.wait_for_dispatch_run(
        prepared.owner, prepared.name, prepared.workflow_id, prepared.baseline_branch,
        prepared.baseline_sha, dispatched_after=started,
    )
    save('dispatched.json', run)
    print(json.dumps({'run_id': run['id'], 'url': run['html_url']}), flush=True)
    client.wait_for_run_completion(prepared.owner, prepared.name, int(run['id']), timeout_seconds=7200)
    run = client.full_run(prepared.owner, prepared.name, int(run['id']))
    if run.get('head_sha') != prepared.baseline_sha:
        raise RuntimeError('Qualification completed on unexpected revision')
    save('evidence.json', {'evidence_class': 'LIVE_BASELINE_QUALIFICATION', 'fork': asdict(prepared), 'run': run})
    print(json.dumps({'conclusion': run['conclusion'], 'jobs': len(run['jobs'])}), flush=True)
    return 0 if run['conclusion'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
