# Reproducible CI optimization target

This is a small, real Python package used to exercise CI workflow optimization
and patch validation. It is an example target and its deliberate bad edits are
supplied fixtures, not proposed production changes.

## Recorded source version

- Target revision: `12d057cbe2da23ac87368266504681ff1ce62e0b` (`baseline-v1`).
- Workflow: `.github/workflows/ci.yml`
- Required check: `tests`, running `python -m pytest -q`
- Runtime: Python 3.11; pytest 8.3.5
- Package install: `uv sync --locked --extra test`
- Candidate workflow must preserve the required check and its command.

The `baseline-v1` workflow installs the package on every run without a cache.
The legitimate fixture adds pip's supported download cache, keyed by the OS,
Python version, and dependency lock. It saves downloaded package data; it does
not skip installation or tests. The fixture is intentionally narrow and
demonstrates real dependency download/cache work. Whether it improves runner
minutes depends on the actual runner and cache hit rate, so measure it on
matched GitHub Actions runs before making a performance claim.

## Run locally

From this directory, with Python 3.11 and `uv` installed:

```sh
uv sync --locked --extra test
uv run --locked python -m pytest -q
```

The initial `uv sync` fetches the locked pytest dependency. Keep cache
conditions matched when measuring. On GitHub Actions, the baseline has no
explicit cache action; the candidate fixture uses `actions/cache` for pip's
download cache. The baseline workflow installs with pip, while local `uv sync`
is the reproducible developer setup. Cache restore/save outcomes appear in
Actions logs.

## Run the workflow locally

The workflow targets GitHub Actions on `ubuntu-latest`. Its steps are ordinary
shell commands and can be reproduced from this directory:

```sh
uv sync --locked --extra test
uv run --locked python -m pytest -q
```

For a meaningful baseline/candidate timing, use the same runner image, Python
version, source revision, test command, and cache condition;
capture the completed Actions run IDs, required-check conclusions, and each
required job's billable duration. The wall-clock `time` command is secondary
and is not runner-minute evidence. With a fresh per-workflow environment,
runner work includes fetching pytest dependency artifacts and installation;
with a restored download cache, package resolution and installation still
occur but artifact downloads may be served locally. Do not add sleep commands
or remove test work to manufacture a speedup.

## Supplied edit fixtures

Apply each patch only to the exact `baseline-v1` tree. From the main
repository root, run (repeat for each fixture):

```sh
git -C demo_target apply --check --ignore-whitespace ../tests/fixtures/demo_target/patches/cache-pip.patch
```

The cache fixture is expected to be structurally eligible for a measured
experiment. The other supplied examples intentionally violate distinct rules:

- `remove-tests.patch` deletes the required test command and should be rejected.
- `out-of-scope.patch` edits package source when only workflow edits are allowed.
- `mismatched-run.json` describes a candidate run at a different source revision
  from the baseline; the comparison must be marked void.

These are validator and evaluator fixtures, not suggestions for real CI edits.
