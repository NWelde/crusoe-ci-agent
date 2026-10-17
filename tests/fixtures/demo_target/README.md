# Demo target fixture index

All entries here are supplied example data for validator/evaluator development.
They are not production workflow edits. The unified diffs target baseline
`12d057cbe2da23ac87368266504681ff1ce62e0b` in the dedicated `demo_target/`
Git repository. From the main repository root, check applicability with
`git -C demo_target apply --check --ignore-whitespace ../tests/fixtures/demo_target/patches/cache-pip.patch` (repeat for each patch).

- `patches/cache-pip.patch`: legitimate narrow cache change. It preserves the
  install and test commands; it is a measurement candidate, not a guaranteed win.
- `patches/remove-tests.patch`: removes the required test step.
- `patches/out-of-scope.patch`: changes application behavior outside the
  workflow-only edit scope.
- `mismatched-run.json`: synthetic run metadata with incompatible revisions.

Never present fixture metadata as a real GitHub Actions run or real measurement.
