# Demo shot list and engineering proof requests

| Scene | Screen / action | Exact proof to capture | Owner | Status / dependency |
|---|---|---|---|---|
| Goal and target | Pinned `madeintandem/jsonb_accessor` workflow and required test job | `artifacts/bro-15-integration/report.md` for the pinned live-demo Ruby target; `tests/fixtures/demo_target/VERIFICATION.md` separately for the Python fixture | Nathan | Existing local proof; target selection/review still needs confirmation |
| Success rules | Open saved reviewed contract; show required checks and limits | `artifacts/bro-7-contract/success-contract.json`; verify recorded timestamp/review status before recording | Nathan | Artifact exists; show exact values, don't paraphrase unverified fields |
| Safe edit | Run/report accepted cache fixture then rejected `remove-tests.patch` | `artifacts/bro-15-integration/report.json` and rejection reason | Nathan | Local fixture validation; label as supplied case |
| Intended agent flow | CLI demo timeline and report | `artifacts/bro-31-demo/events.jsonl`, report, agent trace | Nathan | SIMULATED data only; label every view |
| Stop behavior | Required-check failure report | `artifacts/bro-15-integration/simulated-required-check-failure/report.md` and `events.jsonl` | Nathan | SIMULATED data only |
| Real GitHub execution | Baseline/candidate runs and sample PR | `artifacts/bro-15-integration/sample-pr-live-evidence.json`, Actions run IDs 39069950743/39069962110, [draft PR #1](https://github.com/NWelde/jsonb_accessor/pull/1) | Nathan | LIVE integration sample; both checks failed; not a win; candidate added runner cost |
| Fork backend | Show CLI help; do not launch new experiment on stage | `uv run ci-agent fork-experiment --help`; code in `src/ci_agent/github/fork_experiment.py` | Nathan | Command is live-capable but not continuous-controller integration |
| Human boundary | Show draft label and explain merge remains human | PR #1 draft metadata and source documentation | Emily | No merge performed |

## Missing / not to imply

- No live fork-and-run has been executed through the new `fork-experiment` command yet.
- The actual live sample above is from the earlier existing-fork script, and its candidate failed; it is not evidence of optimization.
- No continuous scheduler, durable experiment resume controller, independent real-run evaluator, or evidence-gated publisher is connected end to end.
- No real run should be presented as a measured win until the baseline and candidate required checks pass and the agreed repeated comparison is complete.
