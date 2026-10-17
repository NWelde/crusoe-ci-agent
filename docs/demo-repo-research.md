# Demo repository research

Evidence checked: **2026-10-17 (America/Los_Angeles)**. Owner: Emily. Technical reviewer: Nathan.

Status: **In Progress — needs-review**. This is a research handoff, not evidence of a completed optimization. Nathan's target approval is pending before [BRO-32](https://linear.app/brojects/issue/BRO-32/create-a-small-reproducible-workflow-target-and-bad-edit-test-cases) implementation.

## Recommendation

Use **python-dotenv as the primary candidate**, **p-limit as the fallback**, and **Requests as the larger, recognizable comparison candidate**. All three are public libraries with real tests and successful upstream GitHub Actions runs. This gives us two manageable experiments alongside a broader compatibility matrix without introducing application infrastructure.

The first experiment should add dependency-download caching to python-dotenv while preserving every existing test, lint command, coverage check, and matrix entry. Missing explicit caching is verified; a speed or compute improvement is still a hypothesis. Its jobs already run as a matrix, so additional job parallelism is not an established opportunity.

Requests is conditional: its main matrix already caches pip, and its [AI policy](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/.github/AI_POLICY.md) prohibits unsupervised agentic tools interacting with the project. Consider only a team-controlled fork with human oversight, no upstream PRs/comments, preserved attribution, and Nathan's review of that boundary. It is not the recommended first autonomous target.

## Scope and evidence limits

- Research used read-only GitHub API requests and repository source inspection. No candidate repositories were cloned, modified, forked, or executed during this research. No workflows were triggered, maintainers contacted, or PRs opened.
- Successful upstream runs establish that the inspected snapshots have runnable CI upstream. **Independent reproduction in our fork has not been performed.** Fork feasibility below is a source-based assessment, not a passing fork-run claim.
- Historical timings come from existing successful default-branch runs. They are not our measurements, repeated baselines, billed usage, or demonstrated savings.
- The source snapshots below are pinned so workflow lines, test files, and timing evidence can be reviewed together. Floating dependencies and runner images can still change between runs.
- Scope is CI efficiency. Application performance, live resizing of an executing job, selective-test correctness, and paid/larger-runner availability are not established capabilities.

## Candidate comparison

Dates in this document use Pacific time. Runner-minutes are the sum of job `completed_at - started_at`, divided by 60; they exclude initial queue time and are not billing-rounded minutes. Longest-job time is not necessarily workflow wall-clock time.

| Candidate and role | Language and actual tests | License | Maintenance evidence | Successful CI sample | Observed jobs / total runner-minutes / longest job |
| --- | --- | --- | --- | --- | --- |
| [python-dotenv](https://github.com/theskumar/python-dotenv) — primary; modest Python project | Python, pytest via tox; [test_main.py](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/tests/test_main.py), [tox.ini](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/tox.ini) | [BSD-3-Clause](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/LICENSE) | Default-branch [commit](https://github.com/theskumar/python-dotenv/commit/0b2880591780a426b0551436f47a17e7a76d954f), 2026-10-01; successful [PR CI](https://github.com/theskumar/python-dotenv/actions/runs/38761061355), 2026-10-15 | [Run 36831121473](https://github.com/theskumar/python-dotenv/actions/runs/36831121473), 2026-10-01 | 9 / **7.55** / **1.68 min** |
| [p-limit](https://github.com/sindresorhus/p-limit) — fallback; small Node.js project | JavaScript, AVA; [test.js](https://github.com/sindresorhus/p-limit/blob/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb/test.js); test script also runs XO lint and tsd type tests | [MIT](https://github.com/sindresorhus/p-limit/blob/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb/license) | Default-branch [commit](https://github.com/sindresorhus/p-limit/commit/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb), 2026-09-18 | [Run 35384652385](https://github.com/sindresorhus/p-limit/actions/runs/35384652385), 2026-09-18 | 3 / **1.82** / **0.63 min** |
| [Requests](https://github.com/psf/requests) — broader comparison; larger CI workload | Python, pytest with HTTP/TLS fixtures; [test_requests.py](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/tests/test_requests.py), [test_lowlevel.py](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/tests/test_lowlevel.py), [conftest.py](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/tests/conftest.py) | [Apache-2.0](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/LICENSE); preserve [NOTICE](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/NOTICE) | Default-branch [commit](https://github.com/psf/requests/commit/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60), 2026-09-21 (dependency automation) | [Run 35650667084](https://github.com/psf/requests/actions/runs/35650667084), 2026-09-21 | 25 / **64.50** / **4.40 min** |

These are CI workload sizes, not source-code-size measurements. No lines-of-code or test-count census was performed.

## 1. python-dotenv: primary

**Workflow:** [test.yml at the inspected commit](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/.github/workflows/test.yml).

### Verified facts

- [Lines 25–35](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/.github/workflows/test.yml#L25-L35) define seven Linux interpreter jobs plus two Windows jobs.
- [Lines 40–53](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/.github/workflows/test.yml#L40-L53) configure Python, upgrade pip, install tox/tox-gh-actions, and run tox without explicit pip caching.
- [Lines 3–15](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/.github/workflows/test.yml#L3-L15) already restrict push runs to main and cancel superseded runs. Do not propose these as missing features.
- [tox.ini](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/tox.ini#L4-L37) maps interpreters to tests, adds lint/manifest checks on Python 3.13, and runs pytest with coverage. Test dependencies include pytest, pytest-cov, Click, and IPython.

### Setup and repository commands

Use a normal Ubuntu runner and Python 3.13 for a representative pilot that includes the extra lint/manifest checks. The [contribution guide](https://github.com/theskumar/python-dotenv/blob/0b2880591780a426b0551436f47a17e7a76d954f/CONTRIBUTING.md#L8-L19) documents `tox`; the workflow documents its bootstrap commands:

```sh
# Inside a checkout of the pinned commit, using the selected interpreter:
python -m pip install --upgrade pip
python -m pip install tox tox-gh-actions
tox
```

In GitHub Actions, tox-gh-actions uses the matrix interpreter mapping. Outside Actions, bare `tox` can request interpreters not installed locally. A local single-interpreter smoke command, derived from tox.ini, is:

```sh
tox -e py313,lint,manifest
```

Tox handles package building/installing for its environments. The historical CI sample is stronger evidence for these commands than assuming every command in the contribution guide remains current. Commands above were inspected, not run by this research.

### Hypothesis, validation, and risk

**Before:** each fresh job downloads tooling and test dependencies without an explicit persistent pip cache. **After:** restore pip's download/wheel cache, still install dependencies and run the same checks. Hypothesis: warm runs use fewer runner-seconds without losing validation.

Proposed change: add setup-python pip caching with explicit dependency inputs covering `tox.ini` and `pyproject.toml`; scope cache compatibility by runner OS and interpreter. Cache downloaded packages, not an entire tox environment. Confirm the actual cache path used by tox's installers.

Validate cold misses and warm hits separately; preserve the complete nine-job matrix for the final comparison. Compare test collection/results, coverage, lint/manifest outcomes, and resolved dependency versions. Cache restore/save time could exceed download savings; dependency ranges and IPython resolution can change. Existing parallel matrix execution is intentional, and no safe removable job dependency was established.

## 2. p-limit: fallback

**Workflow:** [main.yml at the inspected commit](https://github.com/sindresorhus/p-limit/blob/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb/.github/workflows/main.yml).

### Verified facts and commands

- [Lines 11–22](https://github.com/sindresorhus/p-limit/blob/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb/.github/workflows/main.yml#L11-L22) run Node 20, 22, and 24 on Ubuntu, with `npm install` and `npm test`, without explicit dependency caching.
- [package.json](https://github.com/sindresorhus/p-limit/blob/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb/package.json#L19-L24) defines `npm test` as `xo && ava && tsd` and requires Node >=20. This is a library with no separate application build command in this script.
- [.npmrc](https://github.com/sindresorhus/p-limit/blob/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb/.npmrc) explicitly sets `package-lock=false`; the inspected root has no package-lock.json. A switch to `npm ci` is not a valid drop-in change.
- Existing job metadata shows installation taking **17–19 seconds** and the combined test script **7–10 seconds** in the sampled run. These are historical single-run observations.

Use Ubuntu and Node 22 for an initial smoke check, then preserve all three versions for validation. Commands are taken directly from the repository's workflow and package script, rather than confusing the README's consumer installation command with contributor setup:

```sh
npm install
npm test
```

### Hypothesis, validation, and risk

**Before:** each job installs dependencies without an explicit saved npm download cache. **After:** restore npm's package-download cache and still run the same install, lint, runtime, and type checks.

Use an explicit download-cache key based on package.json, .npmrc, OS, and Node version; do not configure caching that assumes a nonexistent lockfile. Do not cache node_modules across interpreter versions. Log resolved dependencies and keep the baseline/candidate dependency graph equivalent in the experiment harness. Any temporary experimental dependency freeze is a harness control, not a claimed upstream lockfile policy change.

AVA tests include tight elapsed-time assertions and randomized delays in [test.js](https://github.com/sindresorhus/p-limit/blob/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb/test.js#L10-L42). Host contention can cause noise or failures. Cache overhead may erase a small gain. Lint and type checks repeat across Node versions, but their removal is not assumed safe. Keep them unchanged for the first experiment.

## 3. Requests: broader comparison

**Workflow:** [run-tests.yml at the inspected commit](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/.github/workflows/run-tests.yml).

### Verified facts

- [Lines 14–30](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/.github/workflows/run-tests.yml#L14-L30) expand to 23 OS/interpreter combinations and **already enable pip caching**. Windows/PyPy is excluded because of an OpenSSL/Rust installation issue.
- The additional [No Character Detection job](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/.github/workflows/run-tests.yml#L41-L61) and [urllib3 1.x job](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/.github/workflows/run-tests.yml#L63-L83) have no explicit pip cache. They deliberately uninstall detection packages or downgrade urllib3; they are distinct compatibility checks, not duplicate tests to delete.
- Both install with `make` and test with `make ci`. In the sampled run their installation steps took **10 and 15 seconds**, versus **80 and 81 seconds** for tests. Cache-only upside is therefore limited for those jobs.
- The workflow accepts push and pull_request events and has no concurrency block. Duplicate or superseded execution is a possible separate opportunity, but event/context equivalence and policy must be checked before suppressing runs.

### Setup and repository commands

The [contributor guide](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/docs/dev/contributing.rst#L65-L79) asks contributors to fork and run the full suite. The executable setup/test commands come from the repository [Makefile](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/Makefile#L1-L8) and workflow:

```sh
# Ubuntu, Python 3.10 for the two compatibility-job experiments:
make             # default target installs requirements-dev.txt
make ci          # pytest tests --junitxml=report.xml
```

Equivalent commands from those Makefile targets, useful when make is unavailable:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests --junitxml=report.xml
```

To reproduce a compatibility job, retain its intermediate uninstall/downgrade command exactly as written in the linked workflow. Do not run the Makefile's publish target: it uploads releases and is unrelated to this research.

[requirements-dev.txt](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/requirements-dev.txt) includes pytest-httpbin, httpbin, trustme, and editable Requests with SOCKS support. [conftest.py](https://github.com/psf/requests/blob/611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60/tests/conftest.py) wraps HTTPBin fixtures and creates a local TLS server. Allow loopback networking and ephemeral ports. A localhost HTTP service is not a paid HTTP API. This inspection does not prove every test is network-independent.

### Hypothesis, validation, and risk

**Before:** the two special compatibility jobs install without explicit pip caching. **After:** restore pip downloads while keeping package removal/downgrade and the entire suite unchanged.

Start with those two Ubuntu jobs as an explicitly limited pilot. Separate their cache keys as needed; verify installed versions and absence of character-detection packages after setup. A download cache must not restore an installed environment that invalidates either compatibility condition. Run the complete original matrix before claiming a workflow-wide improvement. Do not extrapolate gains from a two-job slice to the 25-job workflow.

Requests is a credible scale example but a weaker caching-first live demo: most jobs already cache, tests dominate the special jobs, some dependency builds require native tooling, and the contribution policy needs human review. No upstream interaction is proposed.

## Fork feasibility, hardware, and selective tests

| Candidate | Fork and access assessment | Hardware/services | Selective-test feasibility |
| --- | --- | --- | --- |
| python-dotenv | Inspected test workflow needs no named secret, deployment environment, or paid API. Static feasibility is good; fork execution remains unverified. Enable Actions in a team-owned fork and confirm action policy/cache access. | Standard CPU runner, Python, filesystem/temp files, subprocesses, package-registry access. No GPU or special hardware is indicated by the inspected test workflow. | pytest can select modules or node IDs, but environment/file handling and shared fixtures create cross-cutting behavior. No reliable change-to-test mapping was established. Keep the full suite and coverage for initial optimization. |
| p-limit | Inspected workflow needs no named secret or service credentials. Static feasibility is good; no team fork access or run is assumed. | Standard Ubuntu CPU runner, Node/npm, registry access. No GPU, database, or paid service is specified. Avoid noisy shared hosts because of timing assertions. | AVA supports focused tests, but this small suite is concentrated in test.js and the test script includes lint/type checks. Little demonstrated benefit from selecting fewer tests; retain all checks. |
| Requests | Inspected test workflow has read-only contents permission and no named secret. Local HTTP fixtures reduce external-service needs. Fork reproduction is unverified and conditional on policy review. Do not enable publication/maintenance workflows as part of the demo. | Standard CPU runners; Ubuntu pilot preferred. Local HTTP/TLS ports required. Native C/Rust/OpenSSL toolchains may be needed when compatible dependency wheels are absent, especially on unusual interpreters. No GPU/paid API is specified in the inspected workflow. | pytest module/node selection is technically possible, but HTTP, proxy, TLS, encoding, and shared-fixture changes can affect many tests. Parallel workers can conflict over fixtures/ports. Do not assume xdist is safe or omit full compatibility tests without separate evidence. |

For all three, public availability and a permissive license do not establish access to a team fork, Actions write permissions, secrets, or Nathan's approval. A future experiment needs a team-controlled repository and appropriately scoped GitHub authentication. Test execution itself does not require a Crusoe key; the reasoning agents' inference is a separate cost and access requirement.

## Runtime and cost: observations versus estimates

| Candidate | Historical upstream observation | Planning estimate: one baseline/candidate pair, with no assumed speedup |
| --- | --- | --- |
| python-dotenv | 7.55 aggregate runner-minutes; longest job 1.68 minutes | About **15.1 runner-minutes** for two full runs; reserve **5–10 minutes wall time**, excluding exceptional queues/download failures. |
| p-limit | 1.82 aggregate runner-minutes; longest job 0.63 minutes | About **3.6 runner-minutes** for two full runs; reserve **2–5 minutes wall time**, excluding exceptional queues. |
| Requests | 64.50 aggregate runner-minutes; longest job 4.40 minutes. The two compatibility jobs together used 3.27 runner-minutes. | About **129 runner-minutes** for two full runs, or **6.5 runner-minutes** for a two-job pilot pair. Reserve **10–20 minutes wall time** for the full pair, **4–8 minutes** for the pilot, plus queues. |

Pair estimates simply double the historical aggregate and assume similar conditions. They are not measured experiment budgets or guaranteed durations. Repeated runs, cache warm-up, slow dependency builds, rate limits, and retries add work; save caps before dispatching anything.

Under [GitHub's billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions), checked 2026-10-17, standard GitHub-hosted runners in public repositories have no runner-minute charge. Thus the proposed public-fork/standard-runner setup has an **estimated $0 GitHub runner-minute charge**, not a measured dollar saving. Larger runners, storage beyond allowances, private copies, and inference can incur separate charges. Their availability and cost are not assumed here.

Report aggregate runner-seconds as compute evidence and workflow elapsed time as latency evidence. Per [design.md](../design.md), workflow elapsed time starts at the first job and ends when all required jobs complete, including intervening waits; report initial queue delay separately. If estimating private-repository cost later, apply the actual rate for each OS/runner class and account plan; do not price a mixed-OS workflow as all Linux.

## Experiment handoff for Nathan and the demo agent

1. **Nathan selects and confirms the target before BRO-32.** Proposed order: python-dotenv, p-limit, then Requests only after its policy/setup review. Workflow URLs and setup requirements are above. No fork or token access is assumed.
2. Establish an unchanged passing baseline in the team fork at the pinned source commit. Confirm installed dependencies, runner/interpreter versions, full test collection, coverage, and required checks. A newly failing baseline blocks improvement claims.
3. Save the experiment rules before measurement: one cache-only change, all checks retained, baseline/candidate order, repetition count, cold/warm treatment, minimum useful gain, failure policy, and runner/time budget. Suggested starting point is five alternating baseline/candidate pairs, plus an explicitly counted warm-up; tune the budget before execution.
4. Keep runner OS/interpreter and resolved dependencies equivalent between variants. Fresh jobs are required; avoid candidate cache writes contaminating baseline caches. Record cache misses/hits and restore/save overhead. Compare cold with cold and warm with warm.
5. Independently validate the diff and results. Compare aggregate runner time and the agreed workflow clock, test counts/results, coverage, lint/type outcomes, and dependency state. Record variability rather than selecting the fastest run. A cache hit or a faster failed run is not success.
6. If the gain is absent or unreliable, retain that negative evidence and try the fallback. Only later implementation may open an evidence-backed PR inside a team-controlled fork after its gates pass; this research authorizes no upstream PR or maintainer contact.

Plain-language hypothesis for the agent: **"Keep exactly the same automated checks, but reuse previously downloaded dependencies so fresh CI jobs may spend less time fetching them. Measure the complete cost of restoring and saving the cache before accepting the change."**

## Unresolved questions and completion boundary

- Which target does Nathan approve, and who owns the experiment fork? Confirmation is not yet recorded.
- Can that account enable the required Actions, restore/save caches, and provide scoped experiment authentication? No access is assumed.
- Does an unchanged fork run pass with the pinned source and current dependency resolution? This has not been independently tested.
- What are the measured cold/warm cache gain, variance, and useful-gain threshold? No optimization result exists yet.
- For Requests, does Nathan accept the team-fork-only use under its AI/contribution policy, and are all test networking/toolchain needs available? If unclear, use python-dotenv or p-limit instead.
- Can selective tests or test parallelism preserve all required behavior? This research establishes neither; keep them out of the first change.
- Larger-runner choices and live resizing remain unverified; neither is required for these candidates.

The candidate comparison, evidence links, recommendation/fallback, executable source commands, and limitations are delivered by this document. Keep the ticket **In Progress / needs-review** until Nathan checks technical feasibility and the remaining acceptance requirements are resolved. Do not mark Nathan's approval, independent fork reproduction, or an optimization result complete based on this research alone. Research review can be completed without claiming measured savings; fork reproduction and BRO-32 implementation must be tracked explicitly rather than implied.

## Timing evidence reproduction (read-only)

The historical totals can be rechecked without executing workflows:

```sh
gh api 'repos/theskumar/python-dotenv/actions/runs/36831121473/jobs?per_page=100'
gh api 'repos/sindresorhus/p-limit/actions/runs/35384652385/jobs?per_page=100'
gh api 'repos/psf/requests/actions/runs/35650667084/jobs?per_page=100'
```

For each successful job, subtract started_at from completed_at and sum the seconds. GitHub's run pages and job metadata remain historical evidence; log/artifact retention and future API availability are not guaranteed.
