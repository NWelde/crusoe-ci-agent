# BRO-32 verification evidence

Target baseline: `12d057cbe2da23ac87368266504681ff1ce62e0b`

## Observed results (local Windows host)

- `uv sync --project demo_target --locked --extra test`: succeeded; resolved the locked target environment and installed pytest 8.3.5.
- From `demo_target/`, `uv run --locked python -m pytest -q`: `5 passed`.
- `git -C demo_target apply --check --ignore-whitespace ../tests/fixtures/demo_target/patches/cache-pip.patch`: succeeded.
- Same apply check for `remove-tests.patch`: succeeded.
- Same apply check for `out-of-scope.patch`: succeeded.

A clean clone of the pinned target commit was also created in a temporary directory; `uv sync --locked --extra test` succeeded and `uv run --locked python -m pytest -q` reported `5 passed`. The clone had no pre-existing virtual environment.

The target's own workflow is `.github/workflows/ci.yml`. It runs on GitHub Actions `ubuntu-latest`, installs the package and pinned pytest requirement, then runs the required `tests` check with `python -m pytest -q`. No GitHub Actions run was dispatched for this verification; run IDs and billable runner durations must be captured during the matched live comparison before claiming a performance gain. The mismatched run JSON is explicitly synthetic fixture data.


Ticket handoff: target and fixture deliverables are prepared for review. BRO-32 specifies “Keep In Progress with needs-review until review”; Emily’s usability review is still required before marking the ticket Done.
