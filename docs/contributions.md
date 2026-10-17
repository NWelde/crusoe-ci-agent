# Prior work and event-built contributions

Reference: https://github.com/NWelde/shadow-runner
Reviewed snapshot: 974366782efa7e7e27421d708c66f261b88b14ff
Reference license: MIT.

Reuse is identified below. The complete MIT notice is preserved in `docs/licenses/SHADOW_RUNNER_LICENSE`. Clearly identify modifications made during this hackathon.

## Reuse inventory

| Source at Shadow Runner snapshot | Destination | Reuse and event changes |
| --- | --- | --- |
| `src/triage/repo_profile_input.py::build_dep_graph` | `src/ci_agent/workflows/dependency_graph.py::build_dep_graph` | Adapted workflow `needs` parsing; added package namespace and local type annotations. |
| `src/dag/graph.py::critical_path` | `src/ci_agent/workflows/dependency_graph.py::critical_path` | Adapted weighted dependency-chain calculation; integrated into the simulated observation adapter. |

Source repository: https://github.com/NWelde/shadow-runner

Source commit: `974366782efa7e7e27421d708c66f261b88b14ff`

License: MIT; copyright notice retained in the copied module and full license text is in `docs/licenses/SHADOW_RUNNER_LICENSE`.

## Event-built work

BRO-31 event-built work: local CLI experiment loop, dependency-injected deterministic demo adapters, simulated success and required-check failure paths, per-step event history, and JSON/JSONL/Markdown evidence exports. Demo records are prominently marked SIMULATED and make no live-provider or performance claim.
