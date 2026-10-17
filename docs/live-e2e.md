# Live JSONB end-to-end run

The demo defaults to **Shadow Runner mode**: one baseline/candidate pair,
workflow elapsed time, and a 5% observed-speedup threshold. `--publish-draft`
allows a review draft with the actual result and failed checks disclosed.
Use `--mode research` for the retained three-pair runner-minute policy.

The demo draft is [PR #2](https://github.com/NWelde/jsonb_accessor/pull/2).
Its earliest pair passed all 187 jobs in both runs: 420s baseline versus 330s
candidate, a 21.43% observed elapsed-time reduction. Later JRuby failures remain
disclosed. This is a demo observation, not a verified optimization.

Reuse existing real evidence without dispatching more Actions:

```powershell
uv run ci-agent shadow-report --evidence artifacts/final-e2e-upstream/execution/report.json --output artifacts/new-shadow-demo --publish-draft
```

The earliest complete pair is selected deterministically and all later
observations are retained. The original research report and contract stay intact.

From the repository root, install the Python environment with `uv sync`. Configure
`CRUSOE_API_KEY` and `CRUSOE_MODEL` in the environment or a local `.env` file; see
`.env.example`. Git Credential Manager must have an authenticated GitHub credential
with access to your existing fork and its Actions workflows. Enable Actions on the
fork before starting. The commands create experiment branches and consume Actions
runner time.

Generate the common baseline repairs from the inspected upstream revision:

```powershell
uv run python scripts/prepare_jsonb_baseline.py --source-sha cef7a810a48ce9c3b8a79015591fddfb1a963e5a --output artifacts/jsonb-baseline-fixes.json
```

These repair stale RuboCop directives and pin the JSON dependency below version 3
for compatibility with the Rails matrix. They apply equally to baseline and
candidate and are recorded separately from the optimization. If upstream changes,
inspect and regenerate the repairs against that revision before comparing runs.

Replace `YOUR_ACCOUNT/jsonb_accessor` with your fork. Choose a new output directory
for each fresh experiment:

```powershell
uv run ci-agent live-e2e --repository madeintandem/jsonb_accessor --fork-repository YOUR_ACCOUNT/jsonb_accessor --common-source-files artifacts/jsonb-baseline-fixes.json --output artifacts/jsonb-live-01 --confirm-live-runs
```

This pins upstream source, generates a contract through live Crusoe inference,
independently reviews it, generates and independently reviews the candidate, and
executes one baseline/candidate pair by default. Every pair retains all 187 jobs: lint and
186 test matrix cells. The candidate only changes PostgreSQL readiness polling
from 10 seconds with 5 retries to 1 second with 50 retries. The readiness command
and 5-second probe timeout stay fixed. This preserves interval times retry count;
it does **not** guarantee the same maximum failure deadline because individual
probes can consume their timeout.

After an interruption, repeat the same command and inputs with `--resume`:

```powershell
uv run ci-agent live-e2e --repository madeintandem/jsonb_accessor --fork-repository YOUR_ACCOUNT/jsonb_accessor --common-source-files artifacts/jsonb-baseline-fixes.json --output artifacts/jsonb-live-01 --confirm-live-runs --resume
```

Completed setup records are validated and reused without additional inference.
Execution resumes from saved run evidence and reconciles dispatches. Existing
rejected or inconsistent setup records require inspection instead of overwrite.

Inspect `setup/source.json`, `setup/contract/success-contract.json`, and
`setup/proposal/proposal.json` for source, contract, prompts, model proposal, and
independent review. Future proposal audits also record the configured model
identifier. Credentials and authorization headers are excluded. Execution evidence
and the readable verdict are in `execution/report.json` and `execution/report.md`.

A completed E2E demonstrates that the agent generated, validated, executed, and
evaluated a real proposal. In research mode, a practical win requires all three pairs
to improve and their mean runner-minute reduction to reach 5%. Adoption requires
independent verification of comparable runner/cache conditions. A completed run,
a numerical improvement, and an adoption-ready win are separate results. Cache or
host uncertainty can leave the verdict inconclusive; report it without claiming
proven savings. The paired confidence interval is exploratory with only three pairs.

Add `--publish-draft` to request a review draft. Shadow drafts preserve failed
checks and limitations without requiring a verified win; research drafts retain
the strict independently verified win gate. No mode automatically merges changes.

The existing investigation is pinned to upstream
`cef7a810a48ce9c3b8a79015591fddfb1a963e5a`. Its reviewed contract and candidate are
under `artifacts/final-e2e-upstream`; its execution is under that directory's
`execution` subdirectory. This older setup stores source and proposal records
directly in the directory, whereas the unified command places them under `setup`.
The repaired baseline qualification passed all **187 jobs** in
[GitHub Actions run 39073317555](https://github.com/NWelde/jsonb_accessor/actions/runs/39073317555).
Qualification establishes a working baseline; it does not establish optimization savings.
