"""CLI for a live matched GitHub Actions experiment in an isolated fork.

This creates a separately named fork and consumes Actions minutes. The fork is
retained so its runs remain inspectable; the script does not create a PR or
delete the fork. Candidate validation is expected to happen before invocation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ci_agent.github.fork_experiment import dispatch_matched_runs, prepare_fork_experiment
from ci_agent.github.runs import GitHubClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, help="OWNER/REPO")
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--candidate-workflow", required=True, type=Path,
                        help="Locally reviewed candidate workflow YAML")
    parser.add_argument("--baseline-workflow", type=Path,
                        help="Optional explicit baseline workflow YAML")
    parser.add_argument("--run-key", required=True, help="Experiment identifier for fork and branches")
    parser.add_argument("--output", type=Path, default=Path("artifacts/fork-experiment"))
    parser.add_argument("--confirm-live-runs", action="store_true",
                        help="Required because this creates a fork and runs GitHub Actions")
    args = parser.parse_args()
    if not args.confirm_live_runs:
        parser.error("pass --confirm-live-runs to create a fork and consume GitHub Actions minutes")

    client = GitHubClient.from_git_credential()
    candidate = args.candidate_workflow.read_text(encoding="utf-8")
    baseline = args.baseline_workflow.read_text(encoding="utf-8") if args.baseline_workflow else None
    fork = prepare_fork_experiment(
        client, args.upstream, args.workflow_path, candidate, run_key=args.run_key,
        baseline_workflow=baseline,
    )
    print(f"Prepared {fork.repository} at {fork.base_sha}; running matched workflow variants.", flush=True)
    result = dispatch_matched_runs(client, fork)
    args.output.mkdir(parents=True, exist_ok=True)
    output_file = args.output / f"{args.run_key}-runs.json"
    output_file.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Evidence saved: {output_file}")
    print(f"Fork retained for inspection: https://github.com/{fork.repository}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
