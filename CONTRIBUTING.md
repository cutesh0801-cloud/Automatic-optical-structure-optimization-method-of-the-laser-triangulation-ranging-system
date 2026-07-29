# Contributing

Use Python 3.12 and keep numerical optics independent from PySide6 widgets.

```powershell
uv sync --extra dev
uv run ruff check .
uv run pytest
```

Do not add source papers, workbooks, proprietary manufacturer drawings, or
device-specific runtime code. Camera names in this project are static sensor
specification identifiers; device connection, acquisition, calibration and
measurement workflows are out of scope. New catalog entries must cite an
official product page and leave unverified fields empty.

Changes to a formula require:

1. a source or derivation in `docs/formulas.md`;
2. a numeric regression test;
3. an explicit validity domain and singularity test.

## Releases

Ordinary `main` and tag pushes never publish a release. Version releases are
manual-only and reserved for large, coherent updates; routine fixes and small
features do not change the application version. A maintenance prerelease may
also be triggered by creating a new `release/build-YYYYMMDD.N` branch that
points to the exact latest remote `main` SHA. Published tags, releases, and
assets are never overwritten through the workflow. Complete the appropriate
checklist and partial-failure runbook in
[`docs/release-policy.md`](docs/release-policy.md) before starting the
`Release` workflow.
