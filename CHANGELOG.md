# Changelog

## 2026-10-24

- **Vietlott Tracker 0.3.3**: add daily full-history retraining, training and latest
  prediction-result details on the Ingress page, and a manual retrain button.
- **Vietlott Tracker 0.3.4**: add persisted walk-forward backtests for Mega 6/45 and
  Power 6/55, leakage checks, and normalized log-loss/Brier/top-six reporting.
- **Vietlott Tracker 0.3.5**: add a causal Beta-Binomial frequency expert with a
  fixed-draw-size prior and paired block-bootstrap intervals versus uniform baseline.
- **Vietlott Tracker 0.3.6**: correct expert-to-forecast alignment so Beta-Binomial
  remains a research benchmark outside the production Hedge; invalidate old model state.
- **XSMB Tracker 0.1.6**: add daily full-history retraining, training and latest
  prediction-result details on the Ingress page, and a manual retrain button.
- **XSMB Tracker 0.1.7**: add persisted, incremental walk-forward backtesting with
  pre-outcome forecasts, common-set log-loss/Brier metrics, and leakage regression tests.
- **XSMB Tracker 0.1.8**: add a causal Beta-Binomial/Dirichlet frequency benchmark
  and paired block-bootstrap intervals while retaining the existing production experts.
- **XSMB Tracker 0.1.9**: render older saved training records that predate Brier and
  backtest metrics without failing the Ingress page.
- Keep each add-on's `config.yaml` version aligned with its Python package version.
