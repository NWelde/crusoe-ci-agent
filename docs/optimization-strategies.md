# Evidence-backed optimization strategies

`live-e2e` now discovers eligible changes from a registry, asks the planner to
choose one, generates its candidate, replays its structural validator, requests a
separate proposal review, and uses the existing persisted execution and draft PR
pipeline. No eligible strategy means no candidate and no CI dispatch. There is no
fallback to caching. Contract rules remain sealed before comparison.

| Executable strategy | Evidence used | Transformation |
| --- | --- | --- |
| `parallelism` | Hosted isolated jobs, resolved build/test/script commands, no artifact/output/lifecycle consumers; existing `always()` or `!cancelled()` condition | Remove unnecessary dependencies while preserving failure behavior and every command |
| `checkout_reduction` | Identical adjacent checkouts; or complete supported-source inventory and resolved commands/configuration with no known Git-history consumer | Remove redundant checkout; or reduce fetch depth from 0 to 1 while retaining the working tree |
| `setup_removal` | A later unconditional setup overwrites the runtime before any consumer; or source/command inspection finds no consumer, output or cache | Remove overwritten or unused runtime setup without restricting downstream build/test commands |
| `superseded_cancellation` | Resolved validation/install/build commands and known actions; no deployment environments, secrets, write permissions, persistent lifecycle commands or existing concurrency | Cancel obsolete runs within the same PR or pushed branch/event/workflow; preserve tags, schedules and dispatches |
| `service_readiness` | PostgreSQL service with explicit `pg_isready` probe, timeout, interval and retries | Poll at 1s with proportionally increased retries; preserve the nominal polling budget |

**There is no logging-only eligibility rule.** Real Python, npm, Go and Cargo
build/test commands are analyzed. npm scripts and lifecycle hooks, shell scripts,
working directories and local composite actions are resolved from repository
source. Redundant checkouts and overwritten setup can be removed before arbitrary
downstream workloads because those commands and their final setup/checkout remain
unchanged.

A success-dependent DAG gate is retained: running tests earlier must not silently
change skip/failure behavior. Upstream outputs/artifacts, ancestor-status observers,
self-hosted shared workspaces, deployment work, unknown commands/actions and
unresolved dynamic scripts are rejected where they prevent a safe edit. Unknown
behavior is not relabeled as harmless test work. This supports ordinary CI; it
cannot certify every arbitrary program. Shallow-checkout evidence rules out known
history consumers, not every possible dynamically generated Git invocation, so a
full candidate run and independent review remain mandatory. Source-informed
hypotheses are never treated as proven savings.

No strategy narrows tests, changes check identities, drops matrix cells, changes
runners or isolation boundaries, or removes executable build/test commands.
Static matrices support axes, `include` and `exclude`, following
[GitHub's matrix semantics](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations).
Dynamic matrices still require resolved coverage evidence. Current strategies
preserve job counts. YAML is regenerated semantically; comments/formatting are not
retained. Slow failed PostgreSQL probes can extend the worst-case failure window.

## CLI

Inspect local eligibility without credentials or execution (source root is inferred; `--repository-root` can override it):

```powershell
ci-agent strategies --workflow .github/workflows/ci.yml --output artifacts/my-discovery
```

Inspect a real remote repository through the normal CLI without dispatching runs:

```powershell
ci-agent strategies --repository sindresorhus/p-limit --workflow-path .github/workflows/main.yml --output artifacts/new-readonly-discovery
```

Remote discovery pins the default branch to a commit, or resolves `--revision` to
one. Source scripts/configuration are fetched as data, bounded to 250 relevant
files/1 MB, and checked against Git blob hashes. Truncated inventories disable
whole-source conclusions. `live-e2e` saves `source-evidence.json`, reuses it without
refetching all blobs, and independently checks the immutable inventory and hashes
before execution, setup resume and publication. Common baseline repairs are
included in execution/publication analysis. No source code is executed during
discovery; `.env` files, dependency trees and generated build directories are excluded.

Run the integrated planner, independent verifier and one-pair experiment in your fork:

```powershell
ci-agent live-e2e --repository OWNER/SOURCE --fork-repository YOU/FORK --template config/your-contract-request.json --output artifacts/new-experiment --confirm-live-runs --publish-draft
```

The template supplies the workflow path and exact required job IDs/commands.
`live-e2e` enables the executable registry strategies in its generated contract.
`live-loop --optimization STRATEGY` accepts the same registry names for supplied
candidates and revalidates eligibility before any branch creation or dispatch.
Publication and setup resume revalidate the selected strategy too.

Shadow mode dispatches exactly one baseline and one candidate. It never retries
with three pairs after a disappointing result. `--mode research` is a separate
three-pair policy requiring matched cache evidence. Structured model JSON retries
are not execution retries. Existing experiment receipts block duplicate dispatch.

Timing reports separate initial queue delay, observed job execution span, and the
sum of job durations. Exact DAG critical-path time and per-job queue delay remain
unavailable rather than inferred. Workflow elapsed time can include scheduling
and completion overhead. One pair reports an observation, never causal savings.
Cancellation requires superseded-run history to quantify benefit; an isolated
pair cannot measure avoided obsolete work.

## Reproduce real-workload integration validation

```powershell
python -m pytest tests/unit/test_normal_ci_cli.py -v --basetemp=artifacts/normal-ci-fixtures
```

Four cases invoke the **actual `live-e2e` CLI** through contract generation,
strategy selection, independent review, fork preparation, execution, persistence,
reporting, draft-publication checks and resume. Both variants execute real Pytest
or Node tests, including assertions, in isolated local child processes. Command
stdout and exit codes are retained in `local-test-command-receipts.json`. Every
case verifies the actual tests pass, one pair is used, and resume adds no dispatch.

GitHub transport, model responses, setup/checkout actions and GitHub scheduling
are fixtures; reports say `FIXTURE_GITHUB_TRANSPORT_REAL_PYTEST_AND_NODE_TESTS`.
These validate product integration and actual test execution, **not live Actions
savings**. HTTP requests fail the fixtures. Additional original transport fixtures
remain in `test_strategy_cli_integration.py`; command/source rejection coverage is
in `test_real_workload_strategies.py` and source-attestation coverage is in
`test_source_evidence.py`. Existing live demo branches and artifacts are untouched.

## Assessed ideas that are recommendations only

| Idea | Missing evidence/infrastructure |
| --- | --- |
| Job batching | Setup/isolation compatibility, complete command mapping and stable required-check aggregators |
| Sharding/balancing | Exhaustive test inventory, disjoint complete partitions, timing history and sound isolation |
| Scoped installs | Dependency closure and lifecycle-script equivalence |
| Runner selection | Authorized runner infrastructure, workload-equivalent benchmarks and cost evidence |
| Tool replacement | Matching diagnostics/rules, compatibility and side-by-side full-suite results |
| Selective tests | Sound dependency analysis and equivalent required coverage |

The evaluator/publication boundary can accept a strategy-certified `CoveragePlan`
with different baseline/candidate job counts, identical disjoint logical coverage
units and preserved required-check names. Plans are derived by validators, never
trusted from reports or model output. This is extension support, **not executable
batching or sharding**. Research adoption additionally requires compatible cache
evidence; unsupported evidence remains inconclusive. No tests or isolation
boundaries are reduced to manufacture speed.

Reference data: [Levels of CI](https://starsling.dev/blog/levels-of-ci) provides a
progression of optimization ideas; [Linear's CI playbook](https://starsling.dev/blog/linear-ci)
motivates reducing repeated setup and improving pipeline structure. Their vendor
installation and migration prompts were not executed. No vendor integration,
paid runner migration, upstream write or automatic merge is included here.
