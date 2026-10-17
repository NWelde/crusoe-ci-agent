# BRO-6 smoke evidence

Captured 2026-10-17 at 20:29 UTC with `uv run ci-agent smoke --live`.

## Crusoe Managed Inference

- Status: passed against the live endpoint.
- Endpoint: `https://api.inference.crusoecloud.com/v1`
- Model: `nvidia/NVIDIA-Nemotron-3.5-Super-VL`
- Request: a fixed connectivity prompt asking for `READY`.
- Actual response: `READY`
- Response SHA-256: `c2e3ac47f4a325469c1a2d5f117e463ec943c721986d5d9f09ac4540b7d80526`
- Redacted machine-readable receipt: `artifacts/bro-6-smoke/inference-smoke.json`
- Credentials and authorization headers are not included in the receipt.

## Runner

- Status: passed on the local host using a clean Python child process.
- Runtime: Python 3.11.9
- Actual output: `RUNNER_OK`
- Redacted machine-readable receipt: `artifacts/bro-6-smoke/runner-smoke.json`
- This did not dispatch GitHub Actions. The project intends to use GitHub Actions as the workflow runner; a successful hosted runner run remains outstanding.

## Code verification

- `uv run ruff check .` — passed.
- `uv run pytest -q` — 22 passed.

The live inference request verifies endpoint authentication and model response. It does not yet validate model-specific structured-output behavior against Crusoe; structured parsing and validation are covered by local tests.
