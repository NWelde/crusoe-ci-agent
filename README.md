# CI improvement agent

Done Means Done hackathon project: continuously inspect GitHub Actions, propose caching or parallelism improvements, verify results independently, and open evidence-backed PRs in a team-controlled fork.

Status: design and directory scaffolding only. No application code, dependencies, or executable workflows yet.

Read [design.md](design.md) for the working architecture and data-model graph.

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
