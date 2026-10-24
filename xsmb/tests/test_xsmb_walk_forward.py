"""Walk-forward and leakage tests for XSMB."""
import copy
import json
import sqlite3
from datetime import date, timedelta

import numpy as np
import pytest

import xsmb.backtest as backtest_module
from xsmb import engine, service, web
from xsmb.backtest import MODEL_NAMES, ordered_rows, run_walk_forward
from xsmb.features import FeatureBuilder, build_features
from xsmb.model import ETA, OnlineModel, _forecast_loss


def _history(count=108):
    rows = []
    first_date = date(2020, 1, 1)
    for draw in range(count):
        loto = sorted({(draw * 13 + offset * 17) % 100 for offset in range(12)})
        rows.append(
            {
                "id": f"draw-{draw:04d}",
                "date": (first_date + timedelta(days=draw)).isoformat(),
                "loto": loto,
                "special": (draw * 29 + 7) % 100,
                "prizes": {
                    "ĐB": [f"{(draw * 29 + 7) % 100:05d}"],
                    "G1": ["23456"],
                },
            }
        )
    return rows


def _read_predictions(path, draw_id):
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT target, model, probabilities_json, picks_json, dataset_version, "
            "config_json, actual_json FROM predictions WHERE draw_id = ? "
            "ORDER BY target, model",
            (draw_id,),
        ).fetchall()


def test_history_is_sorted_before_processing():
    rows = _history(5)
    shuffled = [rows[3], rows[0], rows[4], rows[2], rows[1]]

    assert [row["id"] for row in ordered_rows(shuffled)] == [
        row["id"] for row in rows
    ]

    duplicate = rows + [copy.deepcopy(rows[-1])]
    with pytest.raises(ValueError, match="duplicate draw IDs"):
        ordered_rows(duplicate)


def test_features_do_not_change_when_future_draws_change():
    matrix = np.random.default_rng(17).integers(0, 2, size=(130, 100))
    changed = matrix.copy()
    changed[105:] = 1 - changed[105:]

    original_features = build_features(matrix)
    changed_features = build_features(changed)

    np.testing.assert_array_equal(original_features[:105], changed_features[:105])

    builder = FeatureBuilder(100)
    for result in matrix[:105]:
        features = builder.current()
        builder.observe(result)
    np.testing.assert_array_equal(features, original_features[104])


def test_hedge_weights_update_only_from_the_observed_forecast_losses():
    model = OnlineModel(5, 0.2, categorical=True, warmup=1)
    model.ewma[0.99] = np.array([0.9, 0.025, 0.025, 0.025, 0.025])
    model.ewma[0.995] = np.array([0.025, 0.9, 0.025, 0.025, 0.025])
    features = np.zeros((5, model.F), dtype=np.float32)
    label = np.array([0, 0, 1, 0, 0], dtype=np.float64)
    forecasts = model.forecast(features)
    previous_logw = model.logw.copy()
    losses = np.array(
        [_forecast_loss(forecasts[name], label, categorical=True) for name in model.names]
    )

    model.observe(features, label, forecasts)

    np.testing.assert_allclose(model.logw, previous_logw - ETA * losses)
    assert model.scored == 0
    assert not np.allclose(model.weights(), np.full(len(model.names), 1 / len(model.names)))


def test_beta_binomial_candidate_obeys_target_probability_constraints():
    loto = OnlineModel(100, 0.238, warmup=1)
    special = OnlineModel(100, 0.01, categorical=True, warmup=1)
    features = np.zeros((100, loto.F), dtype=np.float32)
    loto_forecast = loto.forecast(features)["beta_binomial"]
    special_forecast = special.forecast(features)["beta_binomial"]

    assert "beta_binomial" not in loto.names
    assert np.all((loto_forecast > 0) & (loto_forecast < 1))
    assert special_forecast.sum() == pytest.approx(1.0)
    assert np.all(special_forecast > 0)

    label = np.zeros(100)
    label[17] = 1
    special.observe(features, label, special.forecast(features))
    restored = OnlineModel.from_dict(special.to_dict())
    assert restored.forecast(features)["beta_binomial"].sum() == pytest.approx(1.0)


def test_walk_forward_predictions_are_saved_for_all_models_before_scoring(tmp_path):
    rows = _history()
    database = tmp_path / "walk-forward.sqlite3"

    result = run_walk_forward(rows, database)

    assert result["processed_draws"] == len(rows)
    assert result["warmup_draws"] == 100
    assert result["scored_draws"] == len(rows) - 100
    saved = _read_predictions(database, rows[100]["id"])
    assert len(saved) == len(MODEL_NAMES) * 2
    assert all(record[2] and record[3] and record[4] and record[5] for record in saved)
    assert all(record[6] is not None for record in saved)
    for target, _, probabilities_json, _, _, _, _ in saved:
        probabilities = np.asarray(json.loads(probabilities_json))
        assert np.all((probabilities > 0) & (probabilities < 1))
        if target == "special":
            assert probabilities.sum() == pytest.approx(1.0)

    for target, summary in result["metrics"].items():
        assert summary["draws"] == len(rows) - 100
        assert set(summary["models"]) == set(MODEL_NAMES)
        assert {metrics["draws"] for metrics in summary["models"].values()} == {
            len(rows) - 100
        }


def test_outcome_is_not_opened_until_all_forecasts_are_committed(tmp_path, monkeypatch):
    rows = _history(101)
    database = tmp_path / "forecast-before-outcome.sqlite3"
    original_outcomes = backtest_module._outcomes
    scored_draw_id = rows[100]["id"]

    def verify_saved_forecasts_before_outcome(row):
        if row["id"] == scored_draw_id:
            with sqlite3.connect(database) as conn:
                records = conn.execute(
                    "SELECT COUNT(*), SUM(actual_json IS NOT NULL) "
                    "FROM predictions WHERE draw_id = ?",
                    (scored_draw_id,),
                ).fetchone()
            assert records == (len(MODEL_NAMES) * 2, 0)
        return original_outcomes(row)

    monkeypatch.setattr(backtest_module, "_outcomes", verify_saved_forecasts_before_outcome)
    run_walk_forward(rows, database)


def test_future_outcomes_cannot_change_an_earlier_forecast(tmp_path):
    rows = _history()
    altered = copy.deepcopy(rows)
    for row in altered[101:]:
        row["loto"] = [(number + 37) % 100 for number in row["loto"]]
        row["special"] = (row["special"] + 53) % 100

    run_walk_forward(rows, tmp_path / "original.sqlite3")
    run_walk_forward(altered, tmp_path / "altered.sqlite3")

    original = _read_predictions(tmp_path / "original.sqlite3", rows[100]["id"])
    changed = _read_predictions(tmp_path / "altered.sqlite3", rows[100]["id"])
    assert [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in original] == [
        (row[0], row[1], row[2], row[3], row[4], row[5]) for row in changed
    ]


def test_backtest_is_reproducible_and_incremental(tmp_path):
    rows = _history()
    database = tmp_path / "incremental.sqlite3"
    run_walk_forward(rows[:105], database)
    before = _read_predictions(database, rows[100]["id"])
    first_metrics = run_walk_forward(rows[:105], database)["metrics"]
    assert _read_predictions(database, rows[100]["id"]) == before

    result = run_walk_forward(rows[:108], database)
    after = _read_predictions(database, rows[100]["id"])
    assert after == before
    next_draw = _read_predictions(database, rows[101]["id"])
    assert {record[4] for record in after}.isdisjoint(
        {record[4] for record in next_draw}
    )
    assert result["processed_draws"] == 108
    assert result["scored_draws"] == 8
    for summary in result["metrics"].values():
        assert summary["draws"] == 8
        assert {scores["draws"] for scores in summary["models"].values()} == {8}
        assert summary["log_loss_definition"]
        assert summary["brier_definition"]
        assert summary["confidence_interval_definition"]
        assert "beta_binomial" in summary["models"]
        assert summary["models"]["base"]["log_loss_delta_vs_base"] == 0
    assert first_metrics["loto"]["draws"] == 5

    repeat_db = tmp_path / "repeat.sqlite3"
    run_walk_forward(rows[:108], repeat_db)
    repeated = _read_predictions(repeat_db, rows[100]["id"])
    assert [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in repeated] == [
        (row[0], row[1], row[2], row[3], row[4], row[5]) for row in after
    ]


def test_changed_processed_history_is_rejected_without_rescoring(tmp_path):
    rows = _history()
    database = tmp_path / "immutable-prefix.sqlite3"
    run_walk_forward(rows, database)
    changed = copy.deepcopy(rows)
    changed[10]["special"] = (changed[10]["special"] + 1) % 100

    with pytest.raises(RuntimeError, match="refusing to rescore"):
        run_walk_forward(changed, database)


def test_engine_keeps_production_training_separate_and_incremental(tmp_path, monkeypatch):
    monkeypatch.setenv("XSMB_HOME", str(tmp_path))
    rows = _history(103)

    first = engine.update(rows[:102], loto_count=5, special_count=3)
    assert first["training"]["backtest_metrics"]["loto"]["draws"] == 2

    second = engine.update(rows[:103], loto_count=5, special_count=3)
    assert second["training"]["backtest_metrics"]["loto"]["draws"] == 3
    assert second["training"]["backtest_metrics"]["special"]["draws"] == 3
    assert second["stats"]["draws"] == 1

    page = web.render()
    assert "Bảng điểm tích lũy" in page
    assert "Backtest Loto" in page
    assert "binary cross-entropy" in page
    assert "bootstrap" in page
    assert all(name in page for name in MODEL_NAMES)

    class SensorRecorder:
        def __init__(self):
            self.states = {}

        def set_state(self, entity, state, attributes):
            self.states[entity] = {"state": state, "attributes": attributes}

    recorder = SensorRecorder()
    service.publish_sensors(recorder, second)
    assert (
        recorder.states["sensor.xsmb_training"]["attributes"]["backtest_metrics"]
        == second["training"]["backtest_metrics"]
    )


def test_web_renders_legacy_training_log_without_brier_or_backtest(monkeypatch):
    monkeypatch.setattr(
        web.engine,
        "load_log",
        lambda: {
            "stats": engine.empty_stats(),
            "pending": None,
            "history": [],
            "training": {
                "full_retrain_this_cycle": False,
                "processed_draws": 101,
                "first_draw": "2020-01-01",
                "last_draw": "2020-04-10",
                "last_full_retrain": "2026-10-24",
                "scored_draws": 1,
                "warmup_draws": 100,
                "expert_log_loss": {"loto": {"base": 0.5}},
            },
        },
    )

    page = web.render()

    assert "log-loss bình quân" in page
    assert "chưa có dữ liệu (sẽ cập nhật ở vòng huấn luyện kế tiếp)" in page
    assert "Báo cáo backtest chưa có trong dữ liệu huấn luyện đã lưu" in page
