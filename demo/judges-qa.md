# Judges' Q&A preparation

## Rapid-response cheat sheet: the ten questions to rehearse first

Ranked by importance and likelihood for this project's 1–2 minute Q&A. Each answer is about 10–15 seconds. This is an honest script for the inspected code; update it only after obtaining the evidence listed below.

| Rank | Likely question | Short spoken answer | Detail |
| --- | --- | --- | --- |
| 1 | Does it actually optimize CI today? | “The checked-in version has the CLI, validated experiment records, and interfaces. The autonomous execution loop is not implemented here, so we cannot claim an end-to-end optimization yet.” | Q1, Q19 |
| 2 | What makes this recursive? | “The intended loop feeds measured outcomes into the next proposal. We have records for linked experiments and outcomes, but the feedback loop itself still needs implementation.” | Q3 |
| 3 | Why use agents instead of scripts? | “Scripts should enforce safety and calculate results. AI is intended for interpreting unfamiliar workflows and choosing hypotheses; we have not yet demonstrated its advantage against a rules-only baseline.” | Q2 |
| 4 | Is the verifier genuinely independent? | “We define a separate verifier interface, but there is no verifier implementation yet. Different role names alone do not establish independent evaluation.” | Q5 |
| 5 | How do you prove a speedup is real? | “The contract specifies three matched pairs and a five-percent threshold. Pair validators check some consistency, but execution controls and statistical evaluation are not implemented yet.” | Q6, Q7 |
| 6 | How much compute or money did you save? | “We have no measured optimization savings. The current success metric is elapsed workflow time; aggregate runner time is separate, and net savings must also include experiments and inference.” | Q9, Q19, Q24 |
| 7 | What happens when a change fails or repeats? | “The models represent failed, invalid, and inconclusive attempts and include patch fingerprints. Durable failure history, retry policy, and duplicate prevention are still implementation work.” | Q4, Q11 |
| 8 | How is Crusoe or NVIDIA actually used? | “Crusoe is the selected inference provider, but this snapshot only checks that settings exist. We have no verified inference call, model identifier, or direct NVIDIA integration.” | Q10, Q27 |
| 9 | What did you build, versus reuse? | “This repository contains the scaffold, data models, interfaces, and tests. The design references earlier Shadow Runner work; its runtime components have not been copied into this snapshot.” | Q15 |
| 10 | Is the recording or dashboard showing real results? | “This checkout contains neither a dashboard nor a recording. Any later demo must label its data source and link the exact commit, CI runs, and PR supporting it.” | Q20 |

## Read this before rehearsing

**Inspected:** 2026-10-17, America/Los_Angeles. Local HEAD and fetched `origin/main` both pointed to **`526e59d4232ac20c4df5a992caecc990c66d0123`**. Read-only fetch confirmed the snapshot; no checkout or implementation code was changed. Only this preparation document is added. No CI run or PR was triggered, no inference request was made, and tests were not executed for this review.

**Critical boundary:** this snapshot is a developer scaffold, not a completed autonomous CI optimizer. [README.md](../README.md) explicitly states that agent reasoning, monitoring, and experiments are not implemented. The `agents`, `github`, `workflows`, `experiments`, `storage`, and `reporting` source directories contain tracked placeholders rather than runtime implementations. [interfaces.py](../src/ci_agent/interfaces.py) defines Python protocols: declarations of methods that implementations must provide, not executable implementations of those methods.

The judging weights below come from the team's supplied brief, not an independently fetched official rulebook: Technicality 40%, Creativity and Originality 25%, Live Demo 20%, Future Potential and AI Impact 15%. The audience descriptions also come from that brief; no individual judge's preferences are assumed.

**Answer timing:** the 28 full answers are written for roughly 15–25 seconds each at a normal speaking pace. Deliver the spoken paragraph first; use the evidence and follow-ups only if asked. In a two-minute exchange, expect to answer three or four questions, not recite the document.

### Evidence map and claim vocabulary

| Label | What it means | Evidence in this snapshot |
| --- | --- | --- |
| **VERIFIED IN CODE** | Source contains the described behavior; not necessarily executed during this review | [cli.py](../src/ci_agent/cli.py): `main`, `smoke`; [models.py](../src/ci_agent/models.py): records and validators; [config.py](../src/ci_agent/config.py): `AgentConfig` |
| **TEST SOURCE PRESENT** | A named unit test checks a limited behavior; no new test-pass claim is implied | [test_cli.py](../tests/unit/test_cli.py), [test_models.py](../tests/unit/test_models.py) |
| **DESIGN ONLY** | A chosen or proposed behavior, not a running feature | [design.md](../design.md), [interfaces.py](../src/ci_agent/interfaces.py), [shared-contract.md](../docs/shared-contract.md) |
| **NEEDS CONFIRMATION** | Missing implementation, runtime trace, result, teammate decision, or external evidence | State exactly what is missing in each question below |

Observed implementation inventory:

- `cli.smoke` checks SQLite with an **in-memory** `SELECT 1`. With `--live`, it checks four environment settings, then explicitly says network connectivity has not been tested. It does not authenticate with GitHub or Crusoe.
- `SuccessContract` stores a metric, required checks, sample count, gain threshold, reviewed flag, and allowed optimization names. `require_checks_and_samples` rejects an empty required-check list and unequal minimum-sample/max-pair values. Defaults are three pairs and 5%; it does not evaluate runs or require `reviewed=True` before any dispatch.
- `RunPair.matching_pair` checks variant, experiment/pair IDs, matching fixture flags, and equality of the runner **string**. It does not prove hardware, dependency, cache, source, workflow, or execution equivalence.
- `Proposal.fingerprint_patch` hashes patch content and rejects a supplied mismatching fingerprint. `fingerprint_json` hashes canonical JSON. Hashes identify content; they do not establish truthful measurements or trusted provenance.
- `RunMeasurement` stores supplied elapsed, runner, and queue durations. It does not calculate them from GitHub timestamps. `VerdictRecord` stores a supplied outcome and optional uncertainty; it does not calculate or enforce a win.
- There is no committed agent client, coordinator, database implementation, GitHub dispatcher, evaluator, verifier implementation, PR publisher, dashboard, experiment report, or captured inference trace in the inspected tracked tree.
- [.github/workflows/checks.yml](../.github/workflows/checks.yml) defines project lint, unit tests, CLI help, and local smoke checks. This is scaffold CI, not an optimization experiment. No new result is asserted merely because the workflow exists.

## Technicality — 40%

### Q1. What actually runs end to end in this version?

**Criterion:** Technicality; also Live Demo. **Priority:** highest.

**Spoken answer:** “The executable part today is the command-line diagnostic, plus validated records for goals, patches, paired runs, and verdicts. The planning, execution, evaluation, and publishing components are interfaces, not a working loop. That gives us a concrete integration foundation, but it is not yet evidence of autonomous optimization.”

**Technical evidence:** [cli.py](../src/ci_agent/cli.py): `main`, `smoke`; [models.py](../src/ci_agent/models.py): `SharedGoal`, `SuccessContract`, `Experiment`; [interfaces.py](../src/ci_agent/interfaces.py): protocol methods; [README.md](../README.md): implementation status.

**Likely follow-ups:** Can you run one real experiment? Are the working components on a different branch?

**Missing evidence — NEEDS CONFIRMATION:** an integrated runtime entry point, implementation commit, and trace from proposal through real CI and verdict. Ask Nathan whether a newer branch exists before judging.

### Q2. Why does this need AI agents rather than deterministic scripts?

**Criterion:** Technicality.

**Spoken answer:** “For a known missing-cache pattern, a deterministic rule may be enough. Our intended AI role is interpreting unfamiliar workflows and choosing a useful experiment from history. Measurement and acceptance should remain deterministic. We have designed that separation, but we still need a rules-only comparison to demonstrate the value of AI.”

**Technical evidence:** [interfaces.py](../src/ci_agent/interfaces.py): `GoalPlanner.define_contract`, `ChangeProposer.propose`, `PatchValidator.validate`, `ExperimentEvaluator.evaluate`; [design.md](../design.md): coordinator and agent responsibilities. All are boundaries/design, not demonstrated AI reasoning.

**Likely follow-ups:** Which successful hypothesis could a heuristic not find? Does AI improve acceptance rate or just add cost?

**Missing evidence — NEEDS CONFIRMATION:** real structured agent outputs, a deterministic baseline, and comparative valid-win rate/cost on the same workflows. Do not argue that every caching change requires an LLM.

### Q3. What makes the system genuinely recursive?

**Criterion:** Technicality.

**Spoken answer:** “The intended recursion is an evidence-driven feedback loop: an attempt produces measurements and a verdict, and those results shape the next attempt under the same goal. We have parent links and outcome records for that structure. There is no running feedback loop yet, and we are not claiming self-modifying code or model training.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `SharedGoal`, `Experiment.parent_experiment_id`, `run_pairs`, `VerdictRecord`, `ExperimentEvent`; [design.md](../design.md): proposed memory summaries and feedback flow.

**Likely follow-ups:** Show an actual second attempt that changed because the first failed. Is this just a retry loop?

**Missing evidence — NEEDS CONFIRMATION:** linked attempt A/B traces, retrieved history included in the second prompt, and a materially revised hypothesis. A diagram or parent ID alone does not demonstrate recursion.

### Q4. What happens when an optimization fails?

**Criterion:** Technicality.

**Spoken answer:** “The records distinguish a loss, an invalid comparison, and an inconclusive result. That lets us describe a failed change without pretending every failure is a regression. What is still missing is the coordinator that saves those outcomes, decides whether another attempt is justified, and stops when its budget is exhausted.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `Verdict`, `ExperimentStatus`, `Experiment.stop_reason`, `ComponentError.retryable`; [interfaces.py](../src/ci_agent/interfaces.py): `ExperimentStore.save_experiment`, `save_event`. No retry/store implementation is present.

**Likely follow-ups:** What if CI fails due to infrastructure? Can a retry create duplicate runs after a crash?

**Missing evidence — NEEDS CONFIRMATION:** failure classification rules, retry/stopping implementation, persisted failed-run evidence, and crash/reconciliation tests. `retryable` is a field, not a retry mechanism.

### Q5. Is your verifier truly independent from the proposer?

**Criterion:** Technicality.

**Spoken answer:** “Not yet in this implementation. We define separate proposing and verifying interfaces, and the verifier is intended to inspect the contract, measured verdict, and evidence. Real independence requires separate execution context and enforced gates. Using the same model with different role labels would not, by itself, establish independent verification.”

**Technical evidence:** [interfaces.py](../src/ci_agent/interfaces.py): `ChangeProposer.propose`, `IndependentVerifier.verify`, `ExperimentEvaluator.evaluate`. Verifier inputs include experiment, contract, verdict, and evidence; prompts, clients, and access controls are absent.

**Likely follow-ups:** Can the verifier inspect raw logs? Can it reject the evaluator or override a failed check? Does it see the proposer's narrative?

**Missing evidence — NEEDS CONFIRMATION:** verifier implementation, model/context separation, evidence-read permissions, deterministic publish gate, and tests rejecting misleading proposer claims. No claim of statistically independent model errors is supportable.

### Q6. How do you ensure fair baseline-versus-candidate experiments?

**Criterion:** Technicality.

**Spoken answer:** “Our pair validator catches mismatched experiment IDs, variants, fixture labels, and runner names. That is useful structural validation, but fairness needs more: equivalent source and dependencies, controlled cache state, consistent hardware, and balanced run order. Those controls are planned; the current pair model does not prove they happened.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `RunPair.matching_pair`, `RunMeasurement`, `Experiment.source_revision`; [test_models.py](../tests/unit/test_models.py): `test_run_pair_rejects_fixture_and_real_run_mix`; [design.md](../design.md): matched conditions policy.

**Likely follow-ups:** How do you prevent a warm candidate cache contaminating the baseline? Does `ubuntu-latest` guarantee identical hardware?

**Missing evidence — NEEDS CONFIRMATION:** executor/environment capture, patch/source equivalence checks, isolated cache namespaces, paired run order, actual runner metadata, and complete samples. Equal runner strings are not hardware proof.

### Q7. Are three pairs and a five-percent threshold statistically convincing?

**Criterion:** Technicality.

**Spoken answer:** “They are initial policy defaults, not a statistical guarantee. The contract stores three matched pairs and a five-percent useful-gain threshold. We have fields for uncertainty, but no estimator or decision engine yet. We should report every sample and call noisy results inconclusive rather than presenting a threshold crossing as proof.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `SuccessContract.require_checks_and_samples`, `minimum_samples`, `max_run_pairs`, `VerdictRecord.uncertainty_low_wall_clock_seconds`, `uncertainty_high_wall_clock_seconds`; [shared-contract.md](../docs/shared-contract.md): default experiment policy.

**Likely follow-ups:** What confidence method do you use? What stops repeated testing until something wins?

**Missing evidence — NEEDS CONFIRMATION:** predeclared estimator, validity/stopping rules, paired-sample calculation, variability data, and tests. Non-default equal pair counts are accepted by the model; it neither collects three pairs nor enforces a verdict's sample count.

### Q8. How do you preserve correctness and security when editing CI?

**Criterion:** Technicality.

**Spoken answer:** “The contract names required checks and allowed optimization types, and the design keeps changes inside a team-controlled fork for human review. Those are useful boundaries, but the executable patch validator and publishing gate are missing. Until they exist, we cannot claim the agent prevents weakened tests, credential exposure, or unsafe workflow edits.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `SuccessContract`, `RequiredCheck`, `Proposal.affected_paths`; [interfaces.py](../src/ci_agent/interfaces.py): `PatchValidator.validate`; [design.md](../design.md): fork, credentials, and publish invariants; [.gitignore](../.gitignore): environment-file exclusions.

**Likely follow-ups:** What about prompt injection in logs? Can a patch change permissions, actions, test commands, or secret access?

**Missing evidence — NEEDS CONFIRMATION:** allowlist enforcement, YAML/graph validation, untrusted-content isolation, secret redaction, token scopes, and adversarial tests. Pydantic field validation does not establish workflow semantics or a security sandbox.

### Q9. How do you measure actual runner-minute savings?

**Criterion:** Technicality.

**Spoken answer:** “We distinguish elapsed workflow time from total machine time. Our main contract metric is the span of required jobs; runner-seconds are a separate diagnostic. To claim compute savings, we need complete job-duration accounting for both variants, including experiment overhead. The current models store numbers but do not collect or calculate them.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `SuccessContract.metric`, `RunMeasurement.wall_clock_seconds`, `runner_seconds`, `queue_seconds`, `VerdictRecord.runner_seconds_saved`; [shared-contract.md](../docs/shared-contract.md): wall-clock-first policy; [demo-repo-research.md](../docs/demo-repo-research.md): historical runner-time methodology.

**Likely follow-ups:** Could parallelism reduce waiting while increasing compute? Do you count all jobs or only required checks?

**Missing evidence — NEEDS CONFIRMATION:** timestamp collector, required-job matching, accounting for retries/non-required jobs/cache overhead, and complete before/after results. Proposed aggregate runner-minutes = sum of relevant job execution seconds / 60; this formula is not an implemented function. Do not equate wall-clock gain with billed savings.

### Q10. Which AI model and inference provider are actually running?

**Criterion:** Technicality.

**Spoken answer:** “Crusoe Managed Inference is the selected provider in the design. This checkout has configuration placeholders and a command that checks they are populated; it does not make an inference request. The exact model, endpoint, structured-output handling, and successful provider integration need a real call trace before we describe them as working.”

**Technical evidence:** [.env.example](../.env.example): `CRUSOE_API_KEY`, `CRUSOE_BASE_URL`, `CRUSOE_MODEL`; [cli.py](../src/ci_agent/cli.py): `smoke(live)`; [design.md](../design.md): agent reasoning provider. No inference adapter or model identifier is committed.

**Likely follow-ups:** Which model/version? Is each agent a separate call? What are the latency, token usage, timeout, and parsing behavior?

**Missing evidence — NEEDS CONFIRMATION:** redacted successful request/response with model ID, provider request ID, role/prompt version, latency, usage, and error handling. Do not print or collect API keys for the Q&A.

### Q11. How do you avoid repeating unsuccessful optimizations or triggering yourself forever?

**Criterion:** Technicality.

**Spoken answer:** “We have patch fingerprints, an experiment comparison key, and a field that identifies experiment-origin runs. The intended policy is to remember failed edits and exclude experiment runs from new-idea triggers. Those fields do not enforce that policy yet: database uniqueness, watcher filtering, and restart-safe coordination still need implementation.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `Proposal.fingerprint_patch`, `fingerprint_json`, `Experiment.comparison_key`, `RunSnapshot.origin_experiment_id`; [config.py](../src/ci_agent/config.py): `max_active_experiments`; [design.md](../design.md): storage/trigger invariants.

**Likely follow-ups:** Is the key content-derived or arbitrary? Can two workers claim the same workflow? What changes permit retesting?

**Missing evidence — NEEDS CONFIRMATION:** coordinator key construction, persisted unique constraint, atomic claims, trigger exclusion, invalidation rules, and restart tests. `comparison_key` currently accepts a supplied string; `max_active_experiments` is not a scheduler.

### Q12. Why should a developer trust the generated PR?

**Criterion:** Technicality.

**Spoken answer:** “The intended PR is a small diff linked to its source revision, contract, run pairs, and measured verdict, with human approval before merge. We have evidence-reference and verdict records, but no PR publisher or publish gate. Trust must come from inspectable evidence tied to the exact patch, not the agent's explanation.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `EvidenceReference`, `Proposal.patch_fingerprint`, `VerdictRecord.evidence_fingerprint`; [design.md](../design.md): one open optimization PR per workflow, exact-patch win gate, and human-edit reconciliation. No executable PR creation function is present.

**Likely follow-ups:** Show the PR URL. Can a human edit invalidate the evidence? Does it ever auto-merge?

**Missing evidence — NEEDS CONFIRMATION:** real team-fork PR, publisher implementation, current-head reconciliation, gate tests, and reproducible evidence bundle. Human approval is design policy; no automatic merge should be claimed.

## Creativity and Originality — 25%

### Q13. How is this different from existing CI optimization products?

**Criterion:** Creativity and Originality.

**Spoken answer:** “Caching and job scheduling are established techniques, so we do not claim those are new. Our intended distinction is the closed loop: state success rules, propose a small change, test it, retain failures, and publish evidence. That is a design thesis today; we still need a working comparison to substantiate differentiation.”

**Technical evidence:** [shared-contract.md](../docs/shared-contract.md): goal → contract → experiment → paired runs → verdict; [interfaces.py](../src/ci_agent/interfaces.py): separated proposal, evaluation, and verification interfaces.

**Likely follow-ups:** Which existing product did you benchmark? What is unique besides multiple agents?

**Missing evidence — NEEDS CONFIRMATION:** named, current product comparison and like-for-like evaluation. No competitive benchmark or market-wide novelty claim is supported by this repository; avoid unsupported claims that other products lack verification or memory.

### Q14. Why couldn't engineers do this with Claude Code or Codex?

**Criterion:** Creativity and Originality.

**Spoken answer:** “An engineer using a coding assistant could propose the same workflow edit. Our intended value is operating the repeatable process around it: monitoring, experiment controls, durable history, and evidence for review. Those operational pieces are not implemented here yet, so we should not claim a demonstrated advantage over that workflow.”

**Technical evidence:** [interfaces.py](../src/ci_agent/interfaces.py): proposed `RepositoryReader`, `WorkflowExecutor`, `ExperimentStore` boundaries; [design.md](../design.md): continuous monitoring and bounded experiment policy.

**Likely follow-ups:** Could a single script coordinate a coding assistant? What does multi-agent separation improve?

**Missing evidence — NEEDS CONFIRMATION:** operational implementation, comparison against an engineer-plus-assistant or single-agent baseline, and measured human effort or reliability. This answer makes no claim about specific current capabilities of either external product.

### Q15. Which components did you build yourselves during the event?

**Criterion:** Creativity and Originality.

**Spoken answer:** “The checked-in event work includes the project scaffold, validated experiment models, typed interfaces, configuration, and unit tests. The design credits an earlier Shadow Runner project as a potential source of runtime components. Its contribution inventory says no modules were copied yet, so we must distinguish that prior foundation from this event's delivered code.”

**Technical evidence:** [contributions.md](../docs/contributions.md): reference snapshot `974366782efa7e7e27421d708c66f261b88b14ff`, MIT attribution and pending inventory; [models.py](../src/ci_agent/models.py): event-built extension description. Git history: `5bf8ba2` scaffold, `e3bff9e` models, `9ffea42` interfaces, `43b622a` experiment rules.

**Likely follow-ups:** Which exact files were reused? Which prior features already worked? Is all reused work eligible under the event rules?

**Missing evidence — NEEDS CONFIRMATION:** teammate ownership/timeline, any later copy inventory and license notices, and official eligibility confirmation where needed. The contribution document's “directory structure only” summary is stale relative to model/interface commits; acknowledge the discrepancy rather than silently treating it as current.

### Q16. What is technically interesting about this specific domain?

**Criterion:** Creativity and Originality.

**Spoken answer:** “CI gives us a concrete outcome to test, but speed is easy to fake by skipping work or changing conditions. Our design makes the agent state required checks and measurement rules before proposing a patch. The implemented records support that discipline; enforcing it during execution is the engineering challenge still ahead.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `SuccessContract`, `RequiredCheck`, `RunPair`; [shared-contract.md](../docs/shared-contract.md): reviewed rules and versioned experiment relationship.

**Likely follow-ups:** Can the agent weaken its own contract? Does the model prove that required checks ran?

**Missing evidence — NEEDS CONFIRMATION:** approval/version lifecycle, immutable persisted contracts, check-preservation validator, and dispatch/publish enforcement. A frozen object can be replaced with another object; field immutability alone does not lock operational policy.

### Q17. Does the system learn from experience, or just keep logs?

**Criterion:** Creativity and Originality.

**Spoken answer:** “The intended learning is using recorded experiments to improve the next decision, not training model weights. We represent outcomes, explanations, parent attempts, and content fingerprints. There is no implemented retrieval or durable store yet, so we can describe the memory design but cannot claim the system has learned from an actual failure.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `Experiment`, `VerdictRecord.explanation`, `ExperimentEvent`; [interfaces.py](../src/ci_agent/interfaces.py): `ExperimentStore`; [design.md](../design.md): compact memory summary proposal.

**Likely follow-ups:** Show history influencing a prompt. How do you handle stale knowledge after dependencies or workflow changes?

**Missing evidence — NEEDS CONFIRMATION:** persisted records, retrieval code, prompt trace, workflow/source invalidation, and an ablation with history disabled. Logging alone is not demonstrated learning.

### Q18. How would you show that the verifier rejects a convincing but bad optimization?

**Criterion:** Creativity and Originality; also Technicality.

**Spoken answer:** “A strong demonstration would include a change that runs faster by removing a required check and show the system rejecting it. The existing unit tests reject some malformed records and mixed fixture/live pairs. They do not test an actual bad workflow patch yet, so that negative demonstration remains an important missing piece.”

**Technical evidence:** [test_models.py](../tests/unit/test_models.py): `test_proposal_computes_and_checks_patch_fingerprint`, `test_run_pair_rejects_fixture_and_real_run_mix`, `test_success_contract_requires_checks_and_feasible_sample_count`; [interfaces.py](../src/ci_agent/interfaces.py): `PatchValidator.validate`.

**Likely follow-ups:** Does it reject `continue-on-error`, removed matrix entries, changed test commands, or forged measurements?

**Missing evidence — NEEDS CONFIRMATION:** end-to-end negative cases for skipped tests, invalid dependency ordering, altered permissions, cache mismatch, and false result claims. Mark synthetic inputs as fixtures; never present them as real GitHub measurements.

## Live Demo — 20%

### Q19. What real improvement have you measured?

**Criterion:** Live Demo.

**Spoken answer:** “There is no completed optimization experiment or before-and-after result in this checkout. Our research document contains historical upstream CI durations for candidate projects, which establish workload context, not savings produced by our agent. We need matched baseline and candidate runs with passing checks before quoting any improvement.”

**Technical evidence:** [demo-repo-research.md](../docs/demo-repo-research.md): evidence limits, upstream run URLs and timing table; [README.md](../README.md): agent/experiment status; tracked `demo` and `reporting` paths contain no existing result artifacts at the inspected commit.

**Likely follow-ups:** What percentage faster? Was that a real repository or a fixture? Can we inspect all samples?

**Missing evidence — NEEDS CONFIRMATION:** real run IDs/attempts, exact source and patch hashes, all paired measurements including failures, deterministic verdict, and independent review. Neither the 5% policy threshold nor historical baseline duration is an achieved improvement.

### Q20. Why is the demo prerecorded, and is the dashboard live?

**Criterion:** Live Demo.

**Spoken answer:** “I cannot confirm a recording or dashboard from this checkout; neither is present. If we use a recording, we should label it and show the captured commit, run IDs, patch, and verdict. That establishes a traceable execution without pretending prerecorded output is a live system, but we still need the actual evidence bundle.”

**Technical evidence:** [design.md](../design.md): dashboard/hosted server deferred; [README.md](../README.md): terminal-first scaffold; inspected tracked `demo` files contain only a placeholder before this document. No dashboard source, data loader, video, or capture manifest was found.

**Likely follow-ups:** Can judges click through to real runs? Are results recorded, fixtures, or live API data? Why was a recording chosen?

**Missing evidence — NEEDS CONFIRMATION:** whether a recording exists, its actual reason, capture timestamp/commit, source data mode, uncut trace, and evidence links. Do not invent a queue-time or demo-reliability justification on behalf of the team.

### Q21. Why did you choose this repository, and can others reproduce the demo?

**Criterion:** Live Demo.

**Spoken answer:** “Our research recommends python-dotenv as a manageable primary target, with p-limit as a quick fallback and Requests as a larger comparison. The document links pinned workflows, tests, and setup commands. We have not confirmed Nathan's selection or reproduced a team-fork run, so reproducibility is assessed from upstream evidence rather than independently demonstrated.”

**Technical evidence:** [demo-repo-research.md](../docs/demo-repo-research.md): candidate table, pinned commits, commands, fork/hardware limitations, Requests policy conditions, and unresolved target approval.

**Likely follow-ups:** Is Requests' main matrix already cached? Does p-limit have a lockfile? Are secrets or GPUs required?

**Missing evidence — NEEDS CONFIRMATION:** Nathan's selected target, team-fork URL/access, clean passing baseline, dependency/runtime snapshot, and replay instructions. Research found existing main-matrix pip caching in Requests and `package-lock=false` in p-limit; avoid invalid generic patches.

### Q22. What does your local smoke test actually prove?

**Criterion:** Live Demo.

**Spoken answer:** “It checks the command-line path and an in-memory SQLite query. With the live flag, it also checks that GitHub and Crusoe settings are present. It deliberately does not make network calls, so a successful smoke check would not establish valid credentials, working inference, repository access, or successful optimization.”

**Technical evidence:** [cli.py](../src/ci_agent/cli.py): `smoke`; [test_cli.py](../tests/unit/test_cli.py): `test_local_smoke_requires_no_credentials`, `test_missing_live_configuration_fails_without_exposing_values`; [.github/workflows/checks.yml](../.github/workflows/checks.yml): project check commands.

**Likely follow-ups:** Does `--live` mean real API calls? Does SQLite persist anything? Have the tests passed on this commit?

**Missing evidence — NEEDS CONFIRMATION:** authenticated API checks, persisted experiment records, and an actual test/CI result if quoting pass counts. Test source was inspected, not executed during this review. The smoke test closes an in-memory database; it does not prove durable storage.

### Q23. What happens if the optimization produces no measurable improvement?

**Criterion:** Live Demo.

**Spoken answer:** “We should report that outcome rather than manufacture a success. The model supports loss and inconclusive verdicts, and the design says to retain effects below the win threshold. But no evaluator enforces those rules yet. For judging, a traceable rejected attempt is credible evidence of evaluation, not evidence of savings.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `Verdict`, `VerdictRecord`, `SuccessContract.report_all_measured_effects`; [shared-contract.md](../docs/shared-contract.md): 5% win policy and reporting smaller effects.

**Likely follow-ups:** What distinguishes no gain from noise? Would you still open a PR? When do you stop?

**Missing evidence — NEEDS CONFIRMATION:** operational decision rule, no-gain sample/report, stopping policy, and publish-gate test. Do not silently relabel invalid evidence as a loss or a small observed gain as a confirmed win.

## Future Potential and AI Impact — 15%

### Q24. How do you account for your own agents' and experiments' costs?

**Criterion:** Future Potential and AI Impact.

**Spoken answer:** “We should compare recurring savings against the full cost of finding them: baseline and candidate runs, failures, retries, inference, and storage. That accounting is not implemented. Also, faster completion can use the same or more compute. We cannot claim financial or net compute savings from an elapsed-time improvement alone.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `RunMeasurement.runner_seconds`, `VerdictRecord.runner_seconds_saved`; [design.md](../design.md): cost analysis deferred and budgets unresolved; [demo-repo-research.md](../docs/demo-repo-research.md): standard-public-runner billing caveat and labeled estimates. No token-cost/agent-call ledger is implemented.

**Likely follow-ups:** What is the break-even run count? Public Actions runs are free, so what dollar saving is real?

**Missing evidence — NEEDS CONFIRMATION:** all experiment runner usage, inference token usage/rates, storage/hosting costs, actual paid runner classes, and expected future run frequency. Proposed net runner-seconds = future runs × verified per-run runner-seconds saved − all experiment runner-seconds. Dollar accounting must additionally price inference and the actual infrastructure; neither calculation currently runs in code.

### Q25. How do you prevent the optimizer consuming more compute than it saves?

**Criterion:** Future Potential and AI Impact.

**Spoken answer:** “Our configuration defaults to one active experiment and three run pairs, but there is no scheduler enforcing those limits yet. Before continuous operation, we need hard limits on dispatched runs, elapsed time, retries, and inference spend. The system should stop or defer when expected value is too small, rather than experimenting indefinitely.”

**Technical evidence:** [config.py](../src/ci_agent/config.py): `AgentConfig.max_active_experiments`, `max_run_pairs_per_experiment`; [models.py](../src/ci_agent/models.py): `SuccessContract.max_run_pairs`, `Experiment.stop_reason`; [shared-contract.md](../docs/shared-contract.md): no agreed minute/elapsed budget.

**Likely follow-ups:** What is the actual cap? Can two workflows exceed it together? Are cancellations and failed runs counted?

**Missing evidence — NEEDS CONFIRMATION:** agreed global/per-experiment hard caps, durable counters, admission control, cancellation, and budget-exhaustion tests. A three-pair target means at least six workflow executions before retries; it is not a runner-minute or dollar ceiling.

### Q26. How would this scale to large enterprise repositories?

**Criterion:** Future Potential and AI Impact.

**Spoken answer:** “The proposed boundary is one goal per workflow and bounded experiments linked by stable IDs. That could support incremental ingestion and carefully limited concurrency. Today there is no ingestion service, database, or enterprise deployment. Scaling would require transactional ownership, rate-limit handling, evidence retention, permission isolation, and tenant-level budgets before we could make reliability claims.”

**Technical evidence:** [models.py](../src/ci_agent/models.py): `RepositorySnapshot`, `WorkflowSnapshot`, `RunSnapshot`, `SharedGoal`; [interfaces.py](../src/ci_agent/interfaces.py): `RepositoryReader`, `ExperimentStore`; [design.md](../design.md): storage uniqueness, atomic workflow claims, external-action reconciliation.

**Likely follow-ups:** How many repositories have you tested? How do you handle merge queues, required checks, matrix expansion, or partial API failures?

**Missing evidence — NEEDS CONFIRMATION:** integration adapters, schema/migrations/transactions, installation-based auth, rate-limit/backoff tests, restart tests, tenant isolation, and load results. One local SQLite writer is a design choice, not an enterprise throughput benchmark.

### Q27. How are Crusoe and NVIDIA meaningfully integrated, and can you resize runners live?

**Criterion:** Future Potential and AI Impact.

**Spoken answer:** “The intended split is Crusoe for reasoning and GitHub Actions for executing tests. This snapshot has no inference client, direct NVIDIA SDK integration, GPU workload, or live runner-resizing implementation. Resource-aware choices are a possible later feature, but provider hardware or an existing job's resizability cannot be inferred from configuration names.”

**Technical evidence:** [design.md](../design.md): technology stack and live-resource limitations; [.env.example](../.env.example): provider placeholders; [pyproject.toml](../pyproject.toml): installed project dependencies; [cli.py](../src/ci_agent/cli.py): configuration-only live mode.

**Likely follow-ups:** Which GPUs run your model? Is an NVIDIA-specific library used? Does inference run on Crusoe during the demo?

**Missing evidence — NEEDS CONFIRMATION:** real Crusoe call trace and model ID; any direct NVIDIA integration and its evidence; actual eligible runner/resource APIs. Do not claim specific serving hardware, accelerated inference, or live resizing without provider/runtime evidence.

### Q28. What are the prototype's biggest limitations and the next convincing milestone?

**Criterion:** Future Potential and AI Impact.

**Spoken answer:** “The main limitation is that the autonomous runtime is not delivered in this snapshot. We have data contracts and unit-test source, not an optimizer result. The next convincing milestone is one authenticated proposal, matched CI experiment, independently checked verdict, and human-review PR, with a failed case also showing that the system refuses an unsafe win.”

**Technical evidence:** [README.md](../README.md): current implementation status; [interfaces.py](../src/ci_agent/interfaces.py): missing implementation boundaries; [test_models.py](../tests/unit/test_models.py): current validation test scope; [shared-contract.md](../docs/shared-contract.md): deliberate boundary.

**Likely follow-ups:** What would you remove to finish? What makes this trustworthy if tests pass but a semantic regression remains?

**Missing evidence — NEEDS CONFIRMATION:** an end-to-end integration commit and evidence bundle. Preserve honest scope: existing tests reduce risk but do not prove semantic equivalence; selective testing, resource telemetry, and enterprise operation remain future work.

## Readiness checklist

### What we can explain confidently from source today

- [x] **Q1, Q22, Q28:** exact scaffold boundary; smoke checks do not prove network connectivity, durable storage, or autonomy.
- [x] **Q6, Q7, Q9:** the validators and declared defaults, with their limits; elapsed time and runner-seconds are different measurements.
- [x] **Q4, Q11, Q17:** outcome vocabulary and content fingerprints exist; persistence, learning, retry, and duplicate enforcement do not.
- [x] **Q5, Q12:** verifier interface and evidence records exist; independence and PR publishing are not implemented.
- [x] **Q21:** candidate research exists, including existing caching in Requests and p-limit's absent lockfile policy. It is not a team-fork experiment.
- [x] **Q15:** current commit history separates scaffold/model/interface work from referenced prior work; no copied runtime modules are declared.

These checks mean “source supports the explanation,” not “the system passed a live demonstration.”

### Technical clarification needed from teammates

- [ ] Confirm whether another branch/repository now contains the runtime; provide its exact commit and re-audit Q1–Q12 before rehearsal.
- [ ] Confirm the Crusoe model, real endpoint/client, agent prompts, context separation, and successful inference trace: Q2, Q5, Q10, Q27.
- [ ] Confirm executor, evaluator/uncertainty method, cache controls, and hard stopping policy: Q4, Q6, Q7, Q23–Q25.
- [ ] Confirm database uniqueness/transactions, durable history, origin filtering, and restart reconciliation: Q3, Q11, Q17, Q26.
- [ ] Confirm recording/dashboard existence and data source; label live, recorded real, or synthetic per view: Q20.
- [ ] Reconcile documentation drift without claiming it is implemented: `AgentConfig.required_checks` accepts an empty tuple although shared-contract prose says config disallows it; only `SuccessContract` checks nonempty required checks. Three/5% are defaults, and `reviewed`/allowed optimization strings are not enforced execution gates. Older design sections retain superseded open questions. This task changes none of those files.

### Claims that require experiment results

- [ ] Any speedup percentage, seconds saved, runner-minute reduction, cost saving, break-even estimate, or claim of lower flakiness: Q7, Q9, Q19, Q24.
- [ ] Fairness evidence: pinned source/patch/contract, all run IDs and attempts, runner/interpreter/dependency conditions, cache states, ordering, queue handling, failures, sample calculation, and uncertainty/stopping method: Q6, Q7.
- [ ] AI or memory advantage over a deterministic/single-agent baseline: Q2, Q13, Q14, Q17.
- [ ] Real rejection of weakened checks, forged evidence, or invalid experiment conditions: Q5, Q8, Q18, Q23.

### Update these answers after real PRs exist

- [ ] **Q12:** insert the team-fork PR URL, base/head SHAs, precise diff, reviewer state, and evidence manifest; do not imply approval or merge that did not occur.
- [ ] **Q19:** add every paired run URL and actual result, including regressions/inconclusive outcomes and measured overhead.
- [ ] **Q20:** attach the capture manifest and data-mode label; show which run/PR is visible in any recording or dashboard.
- [ ] **Q3, Q4, Q11, Q17:** show a prior attempt influencing a later one, with duplicate/stop behavior demonstrated.
- [ ] **Q15:** update attribution for any newly copied Shadow Runner files and distinguish event-built modifications from prior code. Recheck event eligibility rather than assuming it.

### Five highest-value rehearsals

1. **Q1 / Q19 — “Show what actually works and the measured result.”** Start with the snapshot boundary; never substitute upstream timing research for our result.
2. **Q3 / Q4 — “Show the recursion after failure.”** Prepare a concrete trace if one exists; otherwise say the feedback loop is planned.
3. **Q5 / Q8 — “Who stops the proposer from cheating?”** Separate model-role design from enforced deterministic gates.
4. **Q6 / Q7 / Q9 — “Is the win fair, and is it speed or compute?”** Explain paired conditions and metric differences without claiming unimplemented statistics.
5. **Q10 / Q15 — “What did you actually build using Crusoe?”** Know the exact model/call trace and event-built code boundary; say what remains missing.

## Questions for Nathan

1. Is `526e59d` still the right implementation snapshot? If work is elsewhere, which branch/commit should we inspect, and which functions now implement the loop?
2. What exact Crusoe model and endpoint will the demo use? Can we retain one redacted successful call with request ID, latency, token usage, role, and prompt version?
3. Are Planner, Improver, and Verifier separate calls/contexts? What raw evidence can the verifier inspect, what proposer context does it receive, and which deterministic gate prevents it from approving failed checks?
4. Where do paired CI dispatch, polling, job matching, and timestamp calculation live? How are source, dependencies, runner identity, baseline/candidate order, and cache states controlled?
5. What uncertainty/decision method will grade three pairs? Is 5% a policy threshold only, and how will invalid, noisy, or incomplete evidence be classified without adaptive cherry-picking?
6. What are the hard global and per-experiment run/minute/inference limits? Where are they enforced across restarts and concurrent workflows?
7. Where are failed attempts stored, comparison keys constructed, and duplicate claims prevented? What stops experiment-origin runs from starting new experiments indefinitely?
8. Which target and team fork are approved? Has an unchanged baseline passed there? Are we keeping Requests conditional on its policy review and avoiding all upstream submissions?
9. Do we have a real measured experiment, negative case, or team-fork PR? Please provide all run IDs/attempts, source/patch/contract identifiers, complete results, and PR URL—no inferred savings.
10. Is the demo recorded, live, or mixed? Does a dashboard exist outside this checkout, and how are real recorded data and fixtures labeled? What is the team's actual reason for recording?
11. Which Shadow Runner modules or other prior code have actually been incorporated, by whom and when? Where are license notices, modifications, and the event eligibility decision recorded?
12. Is there any direct NVIDIA technology integration or evidence of serving hardware? If not, should we explicitly describe Crusoe inference as the intended integration and make no NVIDIA-specific claim?

## Final rehearsal guardrails

- Do not say “three agents run,” “the verifier rejected it,” “we learned,” “the PR was created,” or “we saved X%” without a trace tied to a specific implementation commit.
- Do not call `smoke --live` an authentication test, a protocol an implementation, a hash proof of authenticity, or a supplied verdict a computed result.
- Do not turn an elapsed-time win into a compute/cost claim. Parallelism can reduce latency without reducing aggregate runner usage.
- Do not infer a real recording, live dashboard, exact model, GPU hardware, or successful integration from the project description.
- The strongest current answer is accurate scope plus inspectable code. Before presenting an optimizer demo as complete, close the runtime, independent evaluation, actual provider call, and real-results evidence gaps above.
