# One-minute demo script

**Concept:** “Done Means Done”: show how an AI-assisted CI optimizer is supposed to improve checks without declaring success when evidence is weak. The demo combines real, inspectable safety and GitHub evidence with a clearly labeled simulated decision loop. It does not claim the continuous product loop is complete.

| Time | Narration | Screen/action | Evidence status |
|---|---|---|---|
| 0–8s | “We want CI to finish sooner, but never by skipping required checks.” | Show the pinned `jsonb_accessor` CI workflow and the required test command. | Verified target/config; saved BRO-7 contract is for this Ruby workflow; `demo_target/` is a separate Python fixture. |
| 8–18s | “Before a change, the system records what success must mean: keep checks enabled and passing, and compare equivalent runs.” | Show the saved BRO-7 contract and its rules. | Real Crusoe-generated/reviewed contract artifact; inspect exact contents before recording. |
| 18–30s | “Here is a tempting shortcut: remove tests. The validator rejects it and says why.” | Run or show BRO-15 report’s `remove-tests.patch` rejection. | Local target validation; supplied fixture, not autonomous live behavior. |
| 30–42s | “The experiment walkthrough shows the intended sequence from observation through proposal, validation, measurement, and decision.” | Show `uv run ci-agent demo-loop` report and event timeline. | **SIMULATED** example; display label throughout. |
| 42–52s | “The live GitHub backend can create an isolated fork, dispatch baseline and candidate workflows, and collect their run evidence.” | Show `ci-agent fork-experiment --help`, then the actual BRO-15 live run pair and draft PR as a separately labeled integration sample. | Backend command verified locally; sample PR/run pair is live but is not a valid speedup and is not the autonomous product loop. |
| 52–60s | “Only a measured win with every required check passing should become a review request. A person decides whether to merge. Our next step is wiring the live executor into the durable controller and independent evaluator.” | Show the retained draft PR, human review boundary, and next-step tickets BRO-10/11/13/14. | PR exists as integration sample; verified-win publication gate still planned. |

## No-win / service-failure wording

“If the baseline fails, runs do not match, a required check fails, or the service is unavailable, we report an invalid or incomplete experiment and stop. We do not turn that into a speedup. The simulated stop path illustrates this policy; the live dispatcher does not yet implement the full continuous stop/retry controller.”

## Recording guardrails

- Keep visible `SIMULATED` labels whenever showing `demo-loop` output.
- Never read out its simulated 8% as a measured result.
- The actual BRO-15 live run pair failed required checks and consumed 11,483 more required runner-seconds in the candidate because its test matrix ran after lint failed. Present it only as an integration/failure observation, not an optimization win.
- Do not call `ci-agent fork-experiment` unattended or continuous; it is a backend command that needs an explicit candidate and confirmation flag.
- The one-minute script is a concept storyboard until Nathan confirms the exact contract and screen capture artifacts and Emily approves first-read clarity.
