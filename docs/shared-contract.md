# Shared data contract

This package defines the event-built contracts around the earlier Shadow Runner snapshot. Shadow Runner's repository/workflow/run/job records describe observed CI. The models in `src/ci_agent/models.py` add the shared goal, reviewed rules, proposals, paired measurements, verdicts, progress events and evidence references needed to conduct autonomous experiments safely.

## Relationship

One `SharedGoal` persists for a workflow. It expresses the product objective: make CI faster while preserving required checks. Each bounded `Experiment` refers to that goal and to one immutable `SuccessContract` version. An experiment contains one `Proposal`, multiple matched `RunPair` measurements, evidence, progress events and one or more verdict records as evidence grows.

```text
RepositorySnapshot -> SharedGoal -> SuccessContract v1
                                      |
                                      +--> Experiment A -> Proposal -> RunPairs -> Verdict
                                      +--> Experiment B -> Proposal -> RunPairs -> Verdict
```

The goal stays shared. Each experiment must contain exactly one hypothesis. The contract is saved before testing and cannot be silently loosened after results are seen. A deliberate rule change creates a new contract version and a new experiment.

## Model groups

- Snapshot: `RepositorySnapshot`, `WorkflowSnapshot`, `RunSnapshot`, `JobSnapshot` retain the observed-project concepts from Shadow Runner.
- Decision inputs: `SharedGoal`, `SuccessContract`, `RequiredCheck`.
- Attempt: `Experiment`, `Proposal`, `RunPair`, `RunMeasurement`.
- Outcome and audit: `VerdictRecord`, `ExperimentEvent`, `EvidenceReference`, `ComponentError`.
- Shared interfaces: `interfaces.py` defines typed protocols for planning, proposing, validating, executing, evaluating, verifying and storing.

Each model carries `schema_version`, rejects unknown fields, is immutable after creation, and serializes through Pydantic's JSON methods. IDs are UUIDs unless sourced from GitHub. Proposal patch fingerprints and canonical JSON fingerprints support duplicate detection. Fixture markers must match across a compared pair, so synthetic fixtures cannot be mixed with live evidence.

## Deliberate first-version defaults

The fixed objective is to reduce GitHub Actions runner minutes while keeping all required checks enabled and passing. Runner minutes are the primary metric and cost proxy; monetary savings are not claimed without billing data. Wall-clock completion time and queue delay may be reported as context but do not determine the verdict. The practical win rule is fixed: all three matched pairs must improve, and the mean reduction must be at least 5%. This is a project decision rule, not proof of statistical certainty. Report a paired 95% confidence interval for the mean reduction alongside all three pair results as exploratory context; at this sample size it does not determine the practical win verdict and must not be described as proof of certainty. Later changes may count for any reduction supported by sufficient measurement evidence. Improvements under 1% may be omitted from highlights but remain in detailed results. Adoption also considers added maintenance and risk. For the selected repository, measure the full required workflow matrix and aggregate runner minutes as the sum across all required jobs and matrix cells. The three-pair contract allows a 24-hour elapsed experiment budget; that cap is wall-clock duration, separate from summed runner minutes. The BRO-31 simulator uses three matched pairs and the same practical win rule only to demonstrate the wiring; its simulated results are not evidence of real CI performance.

`SuccessContract` now records the allowed optimizations, required checks, primary metric, practical win rule, confidence-interval reporting method, sample and attempt budgets, comparison conditions, stop conditions, and selected uncertainty method. Contract generation first applies these locked policy values, then obtains an independent Verifier review. A reviewed contract is saved with a canonical fingerprint; loading the file checks the fingerprint before downstream code can use it. Editing grading rules therefore requires generating and reviewing a new contract version before a new experiment.

An experiment's comparison key is supplied by the coordinator and should be the canonical fingerprint of repository/source revision, workflow fingerprint, patch fingerprint and measurement conditions. A unique persisted key should prevent duplicate experiments; retries that request more evidence extend the same experiment.

## Judge-facing history and dashboard

The final report is not enough. Keep an append-only, timestamped event trail for every observed run and experiment step: what the system observed, the decision made, the concise reason, the evidence used, the exact edit, validation outcome, required-check results, dispatched runs, measurements, retries/stops, and verdict. Link exact before/after workflow content or diffs, GitHub run and PR URLs, logs and artifacts; retain fingerprints so the dashboard can show which version was evaluated. Record agent role and prompt/model version where available, plus a short evidence-based explanation. Do not expose credentials or private hidden chain-of-thought; show a concise decision summary instead. Retries and later evaluations append events and never overwrite the earlier record. The dashboard presents this timeline so judges can follow what the agent saw, decided, changed and learned.

## Example

```python
from ci_agent.models import RequiredCheck, SharedGoal, SuccessContract

goal = SharedGoal(workflow_id="workflow-ci")
contract = SuccessContract(
    goal_id=goal.id,
    version=1,
    required_checks=(RequiredCheck(name="tests"), RequiredCheck(name="lint")),
)
```

This creates illustrative data only; it does not contact GitHub or launch a run.

## Deliberate boundary

These are data contracts, not the autonomous runner or SQLite implementation. They do not dispatch GitHub Actions, enforce database uniqueness/transactions, calculate statistical uncertainty, or publish pull requests. Those components must implement the protocols and use the same records. Actual GitHub adapters translate API data into snapshots; they must not pass unvalidated raw dictionaries across component boundaries.
