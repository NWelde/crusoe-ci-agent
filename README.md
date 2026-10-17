# CI improvement agent

Done Means Done hackathon project: continuously inspect GitHub Actions, propose caching or parallelism improvements, verify results independently, and open evidence-backed PRs in a team-controlled fork.

Status: runnable developer scaffold with locked dependencies, CLI smoke checks and project CI. Optimization agents and experiment workflows are not implemented yet.

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
uv run ruff check .
uv run pytest
```

The default smoke check is local and requires no credentials. It checks that the entry point and SQLite runtime work; it does not test GitHub or Crusoe connectivity.

For future live integration, copy `.env.example` to `.env` and fill in the GitHub token, Crusoe API key, base URL and model. Never commit `.env`. `uv run ci-agent smoke --live` validates that those settings are present without printing their values or making network calls. Actual authentication and inference are separate implementation work.

GitHub Actions runs lint, tests, CLI help and local smoke checks on pushes and PRs without credentials. Agent reasoning, monitoring and experiments are not implemented yet.

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

