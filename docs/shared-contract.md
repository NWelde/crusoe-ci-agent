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

The shared objective is speed while preserving required checks. The main metric is wall-clock time from the earliest required-job start to the latest required-job completion. Queue delay is reported separately. Summed runner seconds are a diagnostic and do not determine the speed verdict. Each experiment runs exactly three matched baseline/candidate pairs on the same runner. The 5% threshold determines whether the result qualifies as a `win`; all measured effects, including smaller improvements and regressions, remain available for the PR report. There is no agreed GitHub Actions minute or elapsed-time budget in this contract. Runtime config disallows an empty required-check list and does not allow fixture runs by default.

An experiment's comparison key is supplied by the coordinator and should be the canonical fingerprint of repository/source revision, workflow fingerprint, patch fingerprint and measurement conditions. A unique persisted key should prevent duplicate experiments; retries that request more evidence extend the same experiment.

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
