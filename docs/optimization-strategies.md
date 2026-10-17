# Evidence-backed optimization strategies

`live-e2e` now discovers eligible changes from a registry, asks the planner to
choose one, generates its candidate, replays its structural validator, requests a
separate proposal review, and uses the existing persisted execution and draft PR
pipeline. No eligible strategy means no candidate and no CI dispatch. There is no
fallback to caching. Contract rules remain sealed before comparison.

| Executable strategy | Evidence required today | Transformation |
| --- | --- | --- |
| `parallelism` | Dependent job already uses `always()`; both endpoints have only literal logging commands, static runners/matrices, no outputs/artifacts/actions | Remove unnecessary DAG dependency while retaining failure-independent execution |
| `checkout_reduction` | Exactly one bare checkout v4; every remaining step is a literal echo; no workflow environment or shell defaults | Remove checkout with no working-tree consumers |
| `setup_removal` | Exactly one setup-node v4/setup-python v5 with a numeric version and no cache/output options; remaining steps are literal logging | Remove unused runtime setup |
| `superseded_cancellation` | Pull-request-only workflow with literal logging jobs, no existing concurrency, no lifecycle side effects | Add cancellation scoped by workflow file/ref and PR; dispatch runs use unique run IDs |
| `service_readiness` | PostgreSQL service with explicit `pg_isready` probe, timeout, interval and retries | Poll at 1s with proportionally increased retries; preserve the nominal polling budget |

The logging-only restrictions are intentional limits of the current soundness
proof. They do **not** establish independence or unused setup in arbitrary test,
lint, deployment, local-action, or repository-script jobs. Those cases are rejected.
PostgreSQL polling is applicable to ordinary service-backed test workflows.
Slow failed probes can extend its worst-case failure window. No strategy changes
test commands, matrix coverage, required-check identities, artifacts or runners.
The current implementations preserve job counts. YAML is regenerated semantically;
comments and original formatting are not retained.

## CLI

Inspect eligibility without credentials or execution:

```powershell
ci-agent strategies --workflow .github/workflows/ci.yml --output artifacts/my-discovery
```

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

## Reproduce the integrated fixtures

```powershell
python -m pytest tests/unit/test_strategy_cli_integration.py -v --basetemp=artifacts/strategy-registry-fixtures
```

All five cases invoke the **actual `live-e2e` CLI** via Click's runner, including
the real contract/proposal generation, separate review calls, fork preparation,
execution loop, persistence, reporting, draft-publication validation and resume.
Only the inference and GitHub transport boundaries are fixtures. Literal check
commands execute in real local child processes. Checkout/setup actions,
PostgreSQL, GitHub scheduling, and the model's structured responses are simulated.
Every report is marked `FIXTURE_TRANSPORT_LOCAL_CHECKS_NOT_LIVE_ACTIONS`; URLs use
`example.invalid`. These validate integration, **not live improvements or measured
Actions savings**. HTTP requests fail the test. Each case asserts exactly two
dispatches and no repeats after resume. Existing live demo branches and artifacts
are untouched.

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
