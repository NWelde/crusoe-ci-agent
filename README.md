# CI improvement agent

Done Means Done hackathon project: continuously inspect GitHub Actions, propose caching or parallelism improvements, verify results independently, and open evidence-backed PRs in a team-controlled fork.

Status: BRO-31 local simulated experiment loop implemented. Live monitoring, real provider adapters, and real-run verdicts are not implemented.

Read [design.md](design.md) for the working architecture and [docs/shared-contract.md](docs/shared-contract.md) for the implemented shared data contract.

## Structure

- src/ci_agent/agents/: Planner, Improver, Verifier
- src/ci_agent/github/: monitoring and GitHub connections
- src/ci_agent/workflows/: parsing, job graphs, allowed edits
- src/ci_agent/experiments/: comparisons, evaluation, orchestration
- src/ci_agent/storage/: SQLite history and progress
- src/ci_agent/reporting/: evidence exports and PR reports
- tests/: unit, integration, and clearly labeled fixtures
- docs/: technical notes and attribution
- demo/: scripts, shot lists, evidence checklist, submission drafts
- config/: configuration templates
- scripts/: developer commands
- .github/workflows/: future project CI

The .reference/ directory is an ignored inspection copy of prior work and is not part of this repository's deliverables.

## Development setup

Install Python 3.11 and uv, then from this repository:

```sh
uv sync --locked
uv run ci-agent --help
uv run ci-agent smoke
uv run ci-agent demo-loop
uv run ruff check .
uv run pytest
```

The default smoke check is local and requires no credentials. It checks that the entry point and SQLite runtime work; it does not test GitHub or Crusoe connectivity.

`uv run ci-agent demo-loop` runs the fixed goal → saved success rules → observation → proposal → validation → matched example comparisons → verdict flow. It writes `events.jsonl`, `report.json`, and `report.md` under `artifacts/bro-31-demo/`. All data is prominently labeled SIMULATED; it contacts no external service and is not proof of real CI improvement. Use `--fail-check` to see the required-check failure stop path, `--consecutive` for the later-improvement threshold, and `--output PATH` to choose another evidence directory. An optional `--config config/demo.json` sets required checks, sample-pair count and highlight threshold; the objective remains fixed.

`scripts/run_demo.ps1` is the BRO-15 acceptance command for the pinned `madeintandem/jsonb_accessor` target. It verifies the target revision and required test command, runs the target's locked local tests, checks that the legitimate cache fixture applies while shortcut/out-of-scope fixtures do not, validates the supplied mismatched-revision example, and records the simulated loop success/stop paths. It writes a local evidence report under `artifacts/bro-15-integration/`. This command does not dispatch GitHub Actions, produce real matched runs, implement durable resume/replan or publish PRs; the report lists those gaps and makes no real performance claim. Run its report assertions with `uv run pytest tests/integration/test_bro15_evidence_report.py` after generating the report.

For Crusoe inference, copy `.env.example` to `.env`, set `CRUSOE_API_KEY` and `CRUSOE_MODEL`, and keep the configured endpoint at `https://api.inference.crusoecloud.com/v1` unless your team has a different approved endpoint. Never commit `.env`. The client uses Crusoe's OpenAI-compatible chat-completions API with a 30-second timeout, at most two retries for transient failures, JSON schema validation for structured calls, and actionable errors that omit response bodies and credentials.

Run `uv run ci-agent inference-smoke` for one real, minimal Crusoe request. It saves the model's short response and a redacted receipt under `artifacts/bro-6-smoke/`. Run `uv run ci-agent runner-smoke` to verify a clean local Python child process; this is explicitly a local-host check, not a GitHub Actions runner test. `uv run ci-agent smoke --live` runs both. The repository's intended workflow execution backend remains GitHub Actions; this command does not dispatch a workflow.

`uv run ci-agent sample-github-runs` reads recent workflow-run metadata and per-job timing from the GitHub Actions REST API using `GITHUB_TOKEN` from the environment or `.env`. It is read-only and saves run snapshots with source revisions, conclusions, required-check results, and summed runner seconds under `artifacts/github-run-sample.json`. This is historical observation; a fair optimization comparison still needs matched baseline/candidate runs on the same revision and runner conditions. The command does not dispatch workflows, create branches, or open PRs.

For the explicitly requested BRO-15 sample, `uv run python scripts/run_sample_pr.py` uses Git Credential Manager to access the existing `NWelde/jsonb_accessor` fork. It creates a sample baseline branch and a candidate branch from the same fork revision, dispatches both real GitHub Actions workflows, waits for completion, saves every paginated job result, then opens a draft PR labeled `[SAMPLE]`. This is a write operation on the fork and consumes Actions runner time. The demonstrated `needs: lint` removal is feedback-latency work, not a runner-minute win; the PR body includes the measured outcome and says not to merge it as a performance optimization. If runs complete but the process is interrupted, `uv run python scripts/finalize_sample_pr.py BASELINE_RUN_ID CANDIDATE_RUN_ID` can collect all job pages and finish/update the draft without rerunning workflows.

`uv run ci-agent contract-generate config/contract-request.example.json` creates a success contract only after Crusoe's Planner proposes complete rules and a separate Verifier approves them. Existing project rules are locked in code: all listed checks stay required and pass, and a practical win requires all three matched pairs to improve runner minutes with a mean reduction of at least 5%. The contract also reports a paired 95% confidence interval as exploratory context; with three pairs it is not proof of statistical certainty and does not change the practical win verdict. The reviewed contract is sealed with a fingerprint and saved before any future proposal.

GitHub Actions runs lint, tests, CLI help and local smoke checks on pushes and PRs without credentials. The Crusoe request is live when `inference-smoke` is run; GitHub Actions job dispatch and experiment execution remain separate integration work.

## Experiment history storage

`ci_agent.storage.SQLiteExperimentStore` persists the shared Pydantic records in a local SQLite database. Create a store with a database path, then save a goal before its contract and an experiment before its proposal, events, verdicts or evidence:

```python
from ci_agent.storage import SQLiteExperimentStore

store = SQLiteExperimentStore(".state/experiments.sqlite3")
store.save_goal(goal)
store.save_contract(contract)
store.save_experiment(experiment)
```

Records are stored as their versioned JSON payload alongside indexed IDs and lookup fields. Foreign keys are enabled, migrations are versioned, and writes use SQLite transactions. Events are append-only and deduplicated by `event_key`; verdicts are retained by evidence fingerprint and evaluation method; evidence references are deduplicated within an experiment. `list_experiments(workflow_id=..., statuses=(...))`, `list_events`, `list_verdicts`, and `list_evidence` retrieve prior history. Use `:memory:` for an ephemeral database. Credentials and raw logs do not belong in the database; store redacted references to external evidence instead.

## Experiment history storage

`ci_agent.storage.SQLiteExperimentStore` persists the shared Pydantic records in a local SQLite database. Create a store with a database path, then save a goal before its contract and an experiment before its proposal, events, verdicts or evidence:

```python
from ci_agent.storage import SQLiteExperimentStore

store = SQLiteExperimentStore(".state/experiments.sqlite3")
store.save_goal(goal)
store.save_contract(contract)
store.save_experiment(experiment)
```

Records are stored as their versioned JSON payload alongside indexed IDs and lookup fields. Foreign keys are enabled, migrations are versioned, and writes use SQLite transactions. Events are append-only and deduplicated by `event_key`; verdicts are retained by evidence fingerprint and evaluation method; evidence references are deduplicated within an experiment. `list_experiments(workflow_id=..., statuses=(...))`, `list_events`, `list_verdicts`, and `list_evidence` retrieve prior history. Use `:memory:` for an ephemeral database. Credentials and raw logs do not belong in the database; store redacted references to external evidence instead.

