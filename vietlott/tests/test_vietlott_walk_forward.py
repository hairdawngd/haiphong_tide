"""Walk-forward and leakage tests for Vietlott."""
import copy
import json
import sqlite3
from datetime import date, timedelta

import numpy as np
import pytest

import vietlott.backtest as backtest_module
from vietlott import engine, service, web
from vietlott.backtest import MODEL_NAMES, ordered_rows, run_walk_forward
from vietlott.features import FeatureBuilder, build_features
from vietlott.online import ETA, OnlineModel, _logloss


def _history(count=108, n=45):
    rows = []
    first_date = date(2020, 1, 1)
    for draw in range(count):
        numbers = sorted({(draw * 13 + offset * 17) % n + 1 for offset in range(6)})
        assert len(numbers) == 6
        rows.append(
            {
                "id": f"draw-{draw:04d}",
                "date": (first_date + timedelta(days=draw)).isoformat(),
                "numbers": numbers,
                "bonus": (draw * 7) % n + 1 if n == 55 else None,
            }
        )
    return rows


def _predictions(path, draw_id):
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT model, probabilities_json, picks_json, dataset_version, "
            "config_json, actual_json FROM predictions WHERE draw_id = ? ORDER BY model",
            (draw_id,),
        ).fetchall()


def test_history_is_sorted_and_duplicate_ids_are_rejected():
    rows = _history(5)
    shuffled = [rows[3], rows[0], rows[4], rows[2], rows[1]]
    assert [row["id"] for row in ordered_rows(shuffled)] == [
        row["id"] for row in rows
    ]
    with pytest.raises(ValueError, match="duplicate draw IDs"):
        ordered_rows(rows + [copy.deepcopy(rows[-1])])


def test_features_do_not_change_when_future_draws_change():
    matrix = np.random.default_rng(23).integers(0, 2, size=(140, 45))
    altered = matrix.copy()
    altered[110:] = 1 - altered[110:]

    first_features = build_features(matrix)
    changed_features = build_features(altered)
    np.testing.assert_array_equal(first_features[:110], changed_features[:110])

    builder = FeatureBuilder(matrix.shape[1])
    for outcome in matrix[:111]:
        features = builder.current()
        builder.observe(outcome)
    np.testing.assert_array_equal(features, first_features[110])


def test_hedge_updates_only_after_observing_forecast_losses():
    model = OnlineModel(45)
    features = np.zeros((45, model.F), dtype=np.float32)
    label = np.zeros(45, dtype=np.float64)
    label[:6] = 1
    forecasts = model.forecast(features)
    prior_logw = model.logw.copy()
    losses = np.array([_logloss(forecasts[name], label) for name in model.names])

    model.observe(features, label, forecasts)

    np.testing.assert_allclose(model.logw, prior_logw - ETA * losses)
    assert model.processed == 1
    assert model.scored == 0


def test_predictions_are_committed_before_actual_results(tmp_path, monkeypatch):
    rows = _history(101)
    database = tmp_path / "walk-forward.sqlite3"
    original_outcome = backtest_module._outcome
    scored_id = rows[100]["id"]

    def check_forecasts_exist_first(row, n):
        if row["id"] == scored_id:
            with sqlite3.connect(database) as conn:
                counts = conn.execute(
                    "SELECT COUNT(*), SUM(actual_json IS NOT NULL) "
                    "FROM predictions WHERE draw_id = ?",
                    (scored_id,),
                ).fetchone()
            assert counts == (len(MODEL_NAMES), 0)
        return original_outcome(row, n)

    monkeypatch.setattr(backtest_module, "_outcome", check_forecasts_exist_first)
    result = run_walk_forward(rows, "mega645", 45, database)
    assert result["scored_draws"] == 1
    saved = _predictions(database, scored_id)
    assert len(saved) == len(MODEL_NAMES)
    assert all(row[1] and row[2] and row[3] and row[4] and row[5] for row in saved)
    for _, probabilities_json, picks_json, _, _, _ in saved:
        probabilities = np.asarray(json.loads(probabilities_json))
        picks = json.loads(picks_json)
        assert len(probabilities) == 45
        assert len(picks) == 6
        assert len(set(picks)) == 6


def test_actual_is_committed_before_model_state_updates(tmp_path, monkeypatch):
    rows = _history(101)
    database = tmp_path / "outcome-before-observe.sqlite3"
    original_observe = OnlineModel.observe
    observed_scored_draw = False

    def check_actual_is_saved(self, features, outcome, forecasts):
        nonlocal observed_scored_draw
        if self.processed >= 100 and not observed_scored_draw:
            with sqlite3.connect(database) as conn:
                actual_count = conn.execute(
                    "SELECT COUNT(*) FROM predictions WHERE actual_json IS NOT NULL"
                ).fetchone()[0]
            assert actual_count == len(MODEL_NAMES)
            observed_scored_draw = True
        return original_observe(self, features, outcome, forecasts)

    monkeypatch.setattr(OnlineModel, "observe", check_actual_is_saved)
    run_walk_forward(rows, "mega645", 45, database)
    assert observed_scored_draw


@pytest.mark.parametrize(("game", "n"), [("mega645", 45), ("power655", 55)])
def test_walk_forward_metrics_are_normalized_and_use_common_draws(tmp_path, game, n):
    rows = _history(108, n)
    result = run_walk_forward(
        rows, game, n, tmp_path / f"{game}.sqlite3", warmup=100
    )
    metrics = result["metrics"]
    assert result["processed_draws"] == 108
    assert result["warmup_draws"] == 100
    assert result["scored_draws"] == 8
    assert metrics["draws"] == 8
    assert set(metrics["models"]) == set(MODEL_NAMES)
    assert {item["draws"] for item in metrics["models"].values()} == {8}
    assert metrics["log_loss_definition"]
    assert metrics["brier_definition"]
    assert metrics["top_six_definition"]
    assert metrics["confidence_interval_definition"]
    assert "beta_binomial" in metrics["models"]
    assert metrics["models"]["base"]["log_loss_delta_vs_base"] == 0
    assert 0 <= metrics["models"]["base"]["top_six_hits_per_draw"] <= 6


def test_beta_binomial_preserves_six_expected_main_numbers_and_round_trips():
    model = OnlineModel(55)
    features = np.zeros((55, model.F), dtype=np.float32)
    forecasts = model.forecast(features)

    assert "beta_binomial" in forecasts
    assert forecasts["beta_binomial"].sum() == pytest.approx(6.0)
    assert np.all((forecasts["beta_binomial"] > 0) & (forecasts["beta_binomial"] < 1))

    label = np.zeros(55, dtype=np.float64)
    label[:6] = 1
    model.observe(features, label, forecasts)
    expected = model.forecast(features)["beta_binomial"]
    restored = OnlineModel.from_dict(model.to_dict())
    restored_forecast = restored.forecast(features)["beta_binomial"]
    assert restored_forecast.sum() == pytest.approx(6.0)
    np.testing.assert_allclose(restored_forecast, expected)
    old_state = model.to_dict()
    old_state["model_version"] -= 1
    with pytest.raises(ValueError, match="Unsupported serialized model version"):
        OnlineModel.from_dict(old_state)


def test_beta_candidate_does_not_shift_existing_expert_names():
    model = OnlineModel(45)
    features = np.zeros((45, model.F), dtype=np.float32)
    label = np.zeros(45)
    label[:6] = 1
    model.observe(features, label, model.forecast(features))
    forecasts = model.forecast(features)

    assert len(model.experts(features)[0]) == len(model.names)
    assert not np.allclose(forecasts["beta_binomial"], forecasts["ewma_0.99"])


def test_future_results_cannot_change_prior_predictions(tmp_path):
    rows = _history()
    altered = copy.deepcopy(rows)
    for row in altered[101:]:
        row["numbers"] = sorted(((number + 9 - 1) % 45) + 1 for number in row["numbers"])

    first_db, altered_db = tmp_path / "first.sqlite3", tmp_path / "altered.sqlite3"
    run_walk_forward(rows, "mega645", 45, first_db)
    run_walk_forward(altered, "mega645", 45, altered_db)
    first, changed = _predictions(first_db, rows[100]["id"]), _predictions(
        altered_db, rows[100]["id"]
    )
    assert [item[:5] for item in first] == [item[:5] for item in changed]


def test_backtest_is_incremental_reproducible_and_rejects_history_edits(tmp_path):
    rows = _history()
    database = tmp_path / "incremental.sqlite3"
    run_walk_forward(rows[:104], "mega645", 45, database)
    prior = _predictions(database, rows[100]["id"])
    run_walk_forward(rows[:108], "mega645", 45, database)
    assert _predictions(database, rows[100]["id"]) == prior
    assert {item[3] for item in prior}.isdisjoint(
        {item[3] for item in _predictions(database, rows[101]["id"])}
    )

    repeated = tmp_path / "repeat.sqlite3"
    run_walk_forward(rows, "mega645", 45, repeated)
    assert [
        item[:5] for item in _predictions(repeated, rows[100]["id"])
    ] == [item[:5] for item in _predictions(database, rows[100]["id"])]

    changed = copy.deepcopy(rows)
    changed[12]["numbers"] = sorted(
        ((number + 1 - 1) % 45) + 1 for number in changed[12]["numbers"]
    )
    with pytest.raises(RuntimeError, match="refusing to rescore"):
        run_walk_forward(changed, "mega645", 45, database)


def test_engine_training_report_is_visible_in_web_and_sensor(tmp_path, monkeypatch):
    monkeypatch.setenv("VIETLOTT_HOME", str(tmp_path))
    rows = _history(103)

    first = engine.update("mega645", rows[:102], 45, 3)
    assert first["training"]["backtest_metrics"]["draws"] == 2
    second = engine.update("mega645", rows[:103], 45, 3)
    assert second["training"]["backtest_metrics"]["draws"] == 3

    page = web.render(["mega645"])
    assert "Backtest" in page
    assert "binary cross-entropy" in page
    assert "bootstrap" in page
    assert all(name in page for name in MODEL_NAMES)

    class SensorRecorder:
        def __init__(self):
            self.states = {}

        def set_state(self, entity, state, attributes):
            self.states[entity] = {"state": state, "attributes": attributes}

    recorder = SensorRecorder()
    service.publish_sensors(recorder, "mega645", second)
    assert (
        recorder.states["sensor.vietlott_mega645_training"]["attributes"][
            "backtest_metrics"
        ]
        == second["training"]["backtest_metrics"]
    )


def test_web_renders_backtest_without_scored_draws(tmp_path, monkeypatch):
    monkeypatch.setenv("VIETLOTT_HOME", str(tmp_path))
    engine.update("mega645", _history(100), 45, 3)

    assert "n/a" in web.render(["mega645"])
