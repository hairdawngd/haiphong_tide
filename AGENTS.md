# Project Guidelines

These instructions apply to every Home Assistant add-on in this repository:
Haiphong Tide, Vietlott Tracker, and XSMB Tracker.

## Structure and runtime

- Each add-on is self-contained under its own directory and has a `config.yaml`,
  `Dockerfile`, and `requirements.txt`. Python code may live in `src/` or directly
  in the add-on directory, as in Haiphong Tide.
- Add-ons currently run on Python 3.12. Keep dependencies in that add-on's
  `requirements.txt`; do not assume a repository-wide `uv` project.
- Keep Home Assistant API access, polling, and service lifecycle consistent with
  neighboring add-ons. Do not expose credentials in logs or responses.

## Add-on releases

- Increment the add-on's `version` in its `config.yaml` for every add-on release.
- Keep the package `__version__` in `src/<package>/__init__.py` aligned with that
  add-on version.
- Update the add-on's `DOCS.md` when configuration, sensors, events, or user-facing
  behavior changes.
- Repository GitHub releases are tag-triggered by `.github/workflows/release.yml`;
  pushing `main` alone does not publish a GitHub Release.

## Python changes and validation

- Follow the patterns and language used by the target add-on. Keep changes scoped
  to the requested add-on unless a shared repository surface also needs updating.
- Add focused tests for behavior changes where practical. Use deterministic
  fixtures and mock network/Home Assistant calls rather than live services.
- For Python changes, run `python -m compileall` on the changed add-on package and
  its focused tests. Run the relevant pytest/flake8 commands from
  `.github/workflows/lint.yml` when available, plus configuration validation for
  changed add-on YAML.
- Preserve user changes already present in the worktree; inspect the diff before
  staging or committing.

## Lottery data and statistical claims

- Vietlott and XSMB are independent lottery products. Do not assume historical
  results predict future draws or describe generated picks as an advantage.
- Respect each game's draw mechanism and probability baseline; do not model
  without-replacement selections as independent selections.
- Keep features causal: a prediction for a draw may use only information available
  before that draw. Evaluate with chronological/walk-forward data and report
  uncertainty, baselines, and limitations.
- Treat training scores as diagnostics, not evidence of future predictive ability.
  Never claim statistical significance or improved odds without a suitable,
  leakage-free out-of-sample analysis.
