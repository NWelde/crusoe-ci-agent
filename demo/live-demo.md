# Three-minute live demo runbook

**Purpose:** demonstrate the trust model and the pieces currently runnable, while making the boundary between live infrastructure and simulated orchestration obvious. No fresh Actions run is required during the three-minute presentation.

## Before presenting

1. Confirm the checked-out commit contains the fork experiment command and the evidence files below exist.
2. Open the pinned target workflow, `artifacts/bro-15-integration/report.md`, `artifacts/bro-31-demo/report.md`, `artifacts/bro-31-failure-demo/report.md`, `artifacts/bro-15-integration/sample-pr-description.md`, and the actual draft PR URL.
3. Verify the local demo target is at the pinned revision named in `tests/fixtures/demo_target/VERIFICATION.md`.
4. Do not execute `fork-experiment` during the timed demo. It creates a GitHub repo and consumes runner minutes. Show `uv run ci-agent fork-experiment --help` or previously captured live run evidence instead.
5. Make a browser/network failure backup: local Markdown/JSON reports with evidence classes visible and a screen capture of the actual GitHub Actions/PR pages. A capture is a replay, not live state.

## Timed run (3:00)

| Time | Operator / speaker | Action and words | Proof / fallback |
|---|---|---|---|
| 0:00–0:25 | Emily | “Done Means Done: make CI faster while preserving the checks that protect correctness.” State that this demo shows a prototype and separates live infrastructure from simulation. | Show target and required check `python -m pytest -q`; if browser unavailable use local target verification. |
| 0:25–1:00 | Nathan | Show legitimate cache patch eligibility, then the remove-tests patch rejection and reason. “The target is pinned; these are local acceptance checks using supplied fixtures.” | `artifacts/bro-15-integration/report.md`; say fixture, not an AI spontaneously discovered attack. |
| 1:00–1:50 | Emily | Show the contract artifact and the simulated loop timeline: goal/rules, observation, proposal, validation, three pairs, verdict. Say “This walkthrough is simulated; the 8% is sample data, not measured performance.” | `artifacts/bro-7-contract/success-contract.json` and `artifacts/bro-31-demo/report.md` (contract is for the Ruby target; demo loop is simulated); local files are the fallback. |
| 1:50–2:25 | Nathan | Show the **live** BRO-15 Actions sample and draft PR. Explain baseline lint failure skipped tests; candidate ran 186 cells, 54 passed/132 failed; candidate used 11,483 additional required runner-seconds. This is a real failure/integration sample, not a performance win. | `artifacts/bro-15-integration/sample-pr-live-evidence.json`, [draft PR](https://github.com/NWelde/jsonb_accessor/pull/1); `sample-pr-description.md` fallback. |
| 2:25–3:00 | Emily | Show the live fork-experiment CLI help and conclude: “The backend can prepare a fork, dispatch matched variants, and collect jobs. Next we connect it to the durable controller and independent verdict gate. A verified win may open a human-review PR; merge remains human.” | `uv run ci-agent fork-experiment --help`; show no-win report if API/network fails. |

## If live service or network fails

Use the saved BRO-15 run report and draft PR screenshot if already captured. Explicitly say “recorded live GitHub evidence, shown as a replay.” Then show the local simulation with its SIMULATED label. Never imply saved evidence is a current live run. Do not substitute an invented success.

## Roles

- **Emily:** story, objective, simulation explanation, conclusion and fallback narration.
- **Nathan:** technical screens, target/fixture boundaries, live run interpretation and CLI capability.

## Exit criteria for this runbook

- Total timing is three minutes when rehearsed.
- Every performance number is read from the live evidence artifact and paired with its failure context.
- The viewer can explain what is real, what is simulated, and what remains to build.
