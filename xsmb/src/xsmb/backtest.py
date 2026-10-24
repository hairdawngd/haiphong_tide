"""Incremental, persisted walk-forward predictions for XSMB."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .data import N_NUMBERS
from .features import FeatureBuilder, WINDOWS
from .model import DECAYS, ETA, L2, LR, MODEL_VERSION, OnlineModel, WARMUP_DRAWS
from .stats import P_LOTO, P_SPECIAL

MODEL_NAMES = (
    "base",
    "beta_binomial",
    "ewma_0.99",
    "ewma_0.995",
    "ewma_0.999",
    "sgd",
    "hedge",
)
TARGETS = ("loto", "special")
METRIC_EPSILON = 1e-12


def ordered_rows(rows):
    if not rows:
        raise ValueError("XSMB history is empty")
    ordered = sorted(rows, key=lambda row: (str(row["date"]), str(row["id"])))
    ids = [str(row["id"]) for row in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("XSMB history contains duplicate draw IDs")
    return ordered


def _canonical_row(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _new_models(warmup):
    return {
        "loto": OnlineModel(N_NUMBERS, P_LOTO, warmup=warmup),
        "special": OnlineModel(N_NUMBERS, P_SPECIAL, categorical=True, warmup=warmup),
    }


def _outcomes(row):
    loto = np.zeros(N_NUMBERS, dtype=np.float64)
    loto[list(set(row["loto"]))] = 1
    special = np.zeros(N_NUMBERS, dtype=np.float64)
    special[int(row["special"])] = 1
    return {"loto": loto, "special": special}


def _model_config(target, model, selection_count):
    return {
        "model_version": MODEL_VERSION,
        "target": target,
        "n_numbers": model.n,
        "base_probability": model.base,
        "categorical": model.categorical,
        "warmup_draws": model.warmup,
        "decays": list(DECAYS),
        "learning_rate": LR,
        "l2": L2,
        "hedge_eta": ETA,
        "feature_windows": list(WINDOWS),
        "selection_count": selection_count,
    }


def _database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            draw_id TEXT NOT NULL,
            draw_date TEXT NOT NULL,
            target TEXT NOT NULL,
            model TEXT NOT NULL,
            predicted_at TEXT NOT NULL,
            probabilities_json TEXT NOT NULL,
            picks_json TEXT NOT NULL,
            dataset_version TEXT NOT NULL,
            config_json TEXT NOT NULL,
            actual_json TEXT,
            PRIMARY KEY (draw_id, target, model)
        );
        CREATE TABLE IF NOT EXISTS backtest_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            processed INTEGER NOT NULL,
            last_draw_id TEXT,
            data_version TEXT NOT NULL,
            models_json TEXT NOT NULL
        );
        """
    )
    return conn


def _init_state(conn, warmup):
    result = conn.execute(
        "SELECT processed, last_draw_id, data_version, models_json "
        "FROM backtest_state WHERE singleton = 1"
    ).fetchone()
    if result is None:
        models = _new_models(warmup)
        conn.execute(
            "INSERT INTO backtest_state VALUES (1, 0, NULL, '', ?)",
            (json.dumps({key: model.to_dict() for key, model in models.items()}),),
        )
        conn.commit()
        return 0, None, "", models

    processed, last_draw_id, data_version, models_json = result
    saved = json.loads(models_json)
    models = {key: OnlineModel.from_dict(value) for key, value in saved.items()}
    if any(model.warmup != warmup for model in models.values()):
        raise ValueError("Backtest warm-up configuration changed; use a new backtest database")
    return processed, last_draw_id, data_version, models


def _restore_features(rows, processed):
    builders = {target: FeatureBuilder(N_NUMBERS) for target in TARGETS}
    digest = hashlib.sha256()
    for row in rows[:processed]:
        for target, outcome in _outcomes(row).items():
            builders[target].observe(outcome)
        digest.update(_canonical_row(row))
        digest.update(b"\n")
    return builders, digest


def _prediction_rows(conn, draw_id):
    return conn.execute(
        "SELECT target, model, probabilities_json FROM predictions "
        "WHERE draw_id = ? ORDER BY target, model",
        (draw_id,),
    ).fetchall()


def _save_forecasts(conn, row, forecasts, selections, dataset_version, warmup):
    draw_id = str(row["id"])
    existing = _prediction_rows(conn, draw_id)
    expected = len(TARGETS) * len(MODEL_NAMES)
    if existing:
        if len(existing) != expected:
            raise RuntimeError(f"Incomplete saved backtest forecasts for draw {draw_id}")
        return {
            target: {
                model: np.asarray(json.loads(probabilities), dtype=np.float64)
                for saved_target, model, probabilities in existing
                if saved_target == target
            }
            for target in TARGETS
        }

    predicted_at = datetime.now(timezone.utc).isoformat()
    records = []
    for target in TARGETS:
        for model_name in MODEL_NAMES:
            probabilities = forecasts[target][model_name]
            count = selections[target]
            picks = np.argsort(-probabilities, kind="stable")[:count].tolist()
            records.append(
                (
                    draw_id,
                    str(row["date"]),
                    target,
                    model_name,
                    predicted_at,
                    json.dumps(probabilities.tolist(), separators=(",", ":")),
                    json.dumps(picks, separators=(",", ":")),
                    dataset_version,
                    json.dumps(
                        _model_config(target, _new_models(warmup)[target], count),
                        separators=(",", ":"),
                    ),
                    None,
                )
            )
    with conn:
        conn.executemany(
            "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
    return forecasts


def _score_metric(probabilities, actual, categorical):
    p = np.clip(probabilities, METRIC_EPSILON, 1 - METRIC_EPSILON)
    if categorical:
        total = p.sum()
        if not np.isclose(total, 1.0, atol=1e-8):
            raise ValueError(f"Categorical probabilities must sum to 1, got {total}")
        log_loss = float(-(actual * np.log(p)).sum())
        brier = float(((p - actual) ** 2).sum())
        return log_loss, brier

    log_loss = float(
        -(actual * np.log(p) + (1 - actual) * np.log1p(-p)).mean()
    )
    brier = float(((p - actual) ** 2).mean())
    return log_loss, brier


def _paired_block_interval(differences, candidate_count, seed=1729, samples=1000):
    values = np.asarray(differences, dtype=np.float64)
    if len(values) < 2:
        return None
    block_length = max(2, int(np.sqrt(len(values))))
    blocks_per_sample = int(np.ceil(len(values) / block_length))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(values), size=(samples, blocks_per_sample))
    offsets = np.arange(block_length)
    indices = (starts[:, :, None] + offsets) % len(values)
    sampled = values[indices.reshape(samples, -1)[:, :len(values)]]
    means = sampled.mean(axis=1)
    tail = 0.05 / (2 * candidate_count)
    return [float(value) for value in np.quantile(means, [tail, 1 - tail])]


def summarize(conn):
    records = conn.execute(
        "SELECT draw_id, draw_date, target, model, probabilities_json, actual_json "
        "FROM predictions WHERE actual_json IS NOT NULL "
        "ORDER BY target, draw_date, draw_id, model"
    ).fetchall()
    metrics = {}
    for target in TARGETS:
        target_records = [record for record in records if record[2] == target]
        ordered_draw_ids = list(dict.fromkeys(record[0] for record in target_records))
        actual_by_draw = {}
        model_draws = {model: set() for model in MODEL_NAMES}
        totals = {
            model: {"log_loss": 0.0, "brier_score": 0.0, "draws": 0}
            for model in MODEL_NAMES
        }
        draw_scores = {
            draw_id: {
                model: {"log_loss": None, "brier_score": None}
                for model in MODEL_NAMES
            }
            for draw_id in ordered_draw_ids
        }
        for draw_id, _, _, model, probabilities_json, actual_json in target_records:
            actual = np.asarray(json.loads(actual_json), dtype=np.float64)
            previous = actual_by_draw.setdefault(draw_id, actual)
            if not np.array_equal(previous, actual):
                raise RuntimeError(f"Inconsistent actual result for draw {draw_id}")
            probabilities = np.asarray(json.loads(probabilities_json), dtype=np.float64)
            log_loss, brier = _score_metric(
                probabilities, actual, categorical=(target == "special")
            )
            totals[model]["log_loss"] += log_loss
            totals[model]["brier_score"] += brier
            totals[model]["draws"] += 1
            draw_scores[draw_id][model] = {
                "log_loss": log_loss,
                "brier_score": brier,
            }
            model_draws[model].add(draw_id)

        expected_draws = set(actual_by_draw)
        if any(draw_ids != expected_draws for draw_ids in model_draws.values()):
            raise RuntimeError(f"Models are not evaluated on a common {target} draw set")
        model_metrics = {}
        for model in MODEL_NAMES:
            count = totals[model]["draws"]
            model_metrics[model] = {
                "draws": count,
                "log_loss": totals[model]["log_loss"] / count if count else None,
                "brier_score": totals[model]["brier_score"] / count if count else None,
            }
            if model == "base":
                model_metrics[model].update(
                    {
                        "log_loss_delta_vs_base": 0.0 if count else None,
                        "log_loss_delta_95_ci_vs_base": [0.0, 0.0] if count > 1 else None,
                        "brier_delta_vs_base": 0.0 if count else None,
                        "brier_delta_95_ci_vs_base": [0.0, 0.0] if count > 1 else None,
                    }
                )
            elif count:
                log_loss_differences = [
                    draw_scores[draw_id][model]["log_loss"]
                    - draw_scores[draw_id]["base"]["log_loss"]
                    for draw_id in ordered_draw_ids
                ]
                brier_differences = [
                    draw_scores[draw_id][model]["brier_score"]
                    - draw_scores[draw_id]["base"]["brier_score"]
                    for draw_id in ordered_draw_ids
                ]
                model_metrics[model].update(
                    {
                        "log_loss_delta_vs_base": float(
                            np.mean(log_loss_differences)
                        ),
                        "log_loss_delta_95_ci_vs_base": _paired_block_interval(
                            log_loss_differences, len(MODEL_NAMES) - 1
                        ),
                        "brier_delta_vs_base": float(
                            np.mean(brier_differences)
                        ),
                        "brier_delta_95_ci_vs_base": _paired_block_interval(
                            brier_differences, len(MODEL_NAMES) - 1
                        ),
                    }
                )
            else:
                model_metrics[model].update(
                    {
                        "log_loss_delta_vs_base": None,
                        "log_loss_delta_95_ci_vs_base": None,
                        "brier_delta_vs_base": None,
                        "brier_delta_95_ci_vs_base": None,
                    }
                )
        if target == "special":
            log_definition = "categorical cross-entropy nats per draw: -sum(y_i * ln(p_i))"
            brier_definition = "multiclass Brier sum per draw: sum((p_i - y_i)^2), 100 classes"
        else:
            log_definition = (
                "binary cross-entropy nats averaged over 100 numbers per draw"
            )
            brier_definition = "binary Brier score averaged over 100 numbers per draw"
        metrics[target] = {
            "draws": len(expected_draws),
            "models": model_metrics,
            "log_loss_definition": log_definition,
            "brier_definition": brier_definition,
            "confidence_interval_definition": (
                "paired circular moving-block bootstrap 95% intervals versus base; "
                "block length sqrt(draws), 1,000 resamples, Bonferroni-adjusted "
                "for six model comparisons; exploratory, not a final untouched holdout"
            ),
        }
    return metrics


def run_walk_forward(rows, database_path, loto_count=5, special_count=3, warmup=WARMUP_DRAWS):
    """Predict each scored draw from its prefix, persist forecasts, then observe its result."""
    ordered = ordered_rows(rows)
    if warmup < 1:
        raise ValueError("warmup must be at least one draw")
    if not 1 <= loto_count <= N_NUMBERS or not 1 <= special_count <= N_NUMBERS:
        raise ValueError("Prediction selection counts must be between 1 and 100")

    conn = _database(database_path)
    try:
        processed, last_draw_id, saved_version, models = _init_state(conn, warmup)
        if processed > len(ordered):
            raise RuntimeError("History is shorter than the committed backtest checkpoint")
        if processed and str(ordered[processed - 1]["id"]) != last_draw_id:
            raise RuntimeError("Historical draw order changed; refusing to replay old forecasts")
        builders, digest = _restore_features(ordered, processed)
        current_version = digest.hexdigest()
        if processed and current_version != saved_version:
            raise RuntimeError("Processed historical data changed; refusing to rescore prior draws")

        selections = {"loto": loto_count, "special": special_count}
        for index in range(processed, len(ordered)):
            row = ordered[index]
            features = {
                target: builders[target].current()
                for target in TARGETS
            }
            if index >= warmup:
                forecasts = {
                    target: models[target].forecast(features[target])
                    for target in TARGETS
                }
                saved_forecasts = _save_forecasts(
                    conn, row, forecasts, selections, digest.hexdigest(), warmup
                )

            if index < warmup:
                outcomes = _outcomes(row)
                for target in TARGETS:
                    forecast = models[target].forecast(features[target])
                    models[target].observe(features[target], outcomes[target], forecast)
            else:
                outcomes = _outcomes(row)
                actual_json = {
                    target: json.dumps(outcomes[target].tolist(), separators=(",", ":"))
                    for target in TARGETS
                }
                with conn:
                    for target in TARGETS:
                        conn.execute(
                            "UPDATE predictions SET actual_json = ? "
                            "WHERE draw_id = ? AND target = ?",
                            (actual_json[target], str(row["id"]), target),
                        )
                for target in TARGETS:
                    models[target].observe(
                        features[target], outcomes[target], saved_forecasts[target]
                    )

            for target in TARGETS:
                builders[target].observe(outcomes[target])
            digest.update(_canonical_row(row))
            digest.update(b"\n")
            last_draw_id = str(row["id"])
            processed = index + 1
            with conn:
                conn.execute(
                    "UPDATE backtest_state SET processed = ?, last_draw_id = ?, "
                    "data_version = ?, models_json = ? WHERE singleton = 1",
                    (
                        processed,
                        last_draw_id,
                        digest.hexdigest(),
                        json.dumps({key: model.to_dict() for key, model in models.items()}),
                    ),
                )

        metrics = summarize(conn)
        scored_draws = max(len(ordered) - warmup, 0)
        return {
            "processed_draws": processed,
            "warmup_draws": min(processed, warmup),
            "scored_draws": scored_draws,
            "first_draw": ordered[0]["date"],
            "last_draw": ordered[-1]["date"],
            "metrics": metrics,
            "database_path": str(database_path),
        }
    finally:
        conn.close()
