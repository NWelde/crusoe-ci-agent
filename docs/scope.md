# Demo scope: Done Means Done

## Goal

Show that an AI-assisted CI optimizer can propose a bounded workflow change, preserve the repository's required checks, and make its decision from measured evidence. A person remains responsible for approving and merging any change.

## Selected demo target and scope correction

The reviewed BRO-7 contract and the available live GitHub Actions sample use **`madeintandem/jsonb_accessor`**, workflow `.github/workflows/ci.yml`, at source revision `12d057cbe2da23ac87368266504681ff1ce62e0b` for the local BRO-15 pinned replay. Its required checks are `lint` (`bundle exec rubocop`) and `tests` (`bundle exec rake db:schema:load && bundle exec rake spec`). The actual live sample in the existing team fork used a later common base SHA recorded in `artifacts/bro-15-integration/sample-pr-live-evidence.json`.

`demo_target/` is a **separate Python fixture** used for local acceptance and adversarial patch tests. Its required command is `python -m pytest -q`. It is not the same workflow/repository as the BRO-7 contract or the actual live sample. Do not present the fixture's `cache-pip.patch` as an optimization against the Ruby contract. The Ruby workflow already uses `actions/setup-ruby` with `bundler-cache: true`; a cache hypothesis for that target needs a new evidence-backed opportunity before it is proposed.

## Decisions and unresolved items

| Decision | Current value | Evidence / status |
|---|---|---|
| Primary story | Preserve required CI checks while investigating runner-minute reduction | Project goal; no successful optimization result yet |
| Reviewed contract target | `madeintandem/jsonb_accessor` Ruby workflow | BRO-7 artifact; required checks are RuboCop and Rake specs |
| Local adversarial fixture | Separate pinned Python `demo_target/` | BRO-32 verification evidence; useful for fixture tests only |
| First optimization type | Not yet confirmed for the Ruby target | Research suggested dependency caching for `python-dotenv`, not the Ruby live sample; inspect actual cache/setup before choosing |
| Required checks | All checks declared by the reviewed target contract remain enabled and pass | No weakening, removal, skip, or unrelated edit is allowed |
| Experiment budget | Contract currently specifies 3 matched pairs, up to 3 attempts, 24-hour experiment cap | These are contract limits; continuous enforcement remains unimplemented |
| First live rehearsal | Backend can dispatch a pair; begin with one explicitly labeled integration pair, not a success verdict | New fork runner has not yet been exercised; one pair cannot satisfy the reviewed 3-pair win rule |
| Pull request | Only a verified win may produce a review request; no automatic merge | Policy; evidence-gated publisher still unimplemented |
| Human merge boundary | Human approval and merge only | Project policy |

## Demo claims and observable proof

1. **Required checks are explicit.** Show the reviewed contract and the matching source workflow.
2. **A supplied shortcut is rejected.** Show the remove-tests fixture and its exact rejection reason; label it as a supplied adversarial case.
3. **The intended decision flow is visible.** Show BRO-31's timeline, continuously label it SIMULATED, and do not state its example 8% as a measurement.
4. **Real GitHub execution has been exercised separately.** Show the actual BRO-15 baseline/candidate run pair and draft PR as a failing integration example. The candidate had 186 test cells (54 passed, 132 failed) after lint failed, adding 11,483 required runner-seconds versus the baseline. This is not an optimization win.
5. **The fork execution backend exists.** Show the command and code; say clearly it is not yet wired into the continuous coordinator and has not yet been exercised by the new command.
6. **A person controls adoption.** Show the draft/review boundary and state that no merge occurred.

## Core and stretch

**Core demo:** reviewed rules → narrow patch gate → matched baseline/candidate GitHub Actions runs → deterministic validity/required-check decision → inspectable evidence → human review boundary. An honest failed/inconclusive result is acceptable and must be reported accurately.

**Stretch:** recurring repository monitoring, multiple targets, adaptive optimization types, live runner sizing, dashboard polish, and automatic post-merge observation. None is needed to present the current concept.

## Success example (illustrative only)

If all required checks remain enabled and pass, the baseline and candidate use the same source and execution conditions, and the complete contract-sized repeated comparison meets its practical rule, the system may recommend a human-reviewed PR with all samples attached. No such win is currently demonstrated. Until then, show the available failed live sample and the clearly labeled simulated walkthrough without claiming a speedup.
