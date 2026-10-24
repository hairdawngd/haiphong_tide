"""Persisted, incremental walk-forward backtesting for Vietlott games."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .data import K
from .features import FeatureBuilder, WINDOWS
from .online import DECAYS, ETA, L2, LR, MODEL_VERSION, START, OnlineModel

MODEL_NAMES = (
    "base",
    "beta_binomial",
    "ewma_0.99",
    "ewma_0.995",
    "ewma_0.999",
    "sgd",
    "hedge",
)
METRIC_EPSILON = 1e-12


def ordered_rows(rows):
    if not rows:
        raise ValueError("Vietlott history is empty")
    ordered = sorted(rows, key=lambda row: (str(row["date"]), str(row["id"])))
    ids = [str(row["id"]) for row in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("Vietlott history contains duplicate draw IDs")
    return ordered


def _canonical_row(row):
    return json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _outcome(row, n):
    numbers = row["numbers"]
    if len(numbers) != K or len(set(numbers)) != K:
        raise ValueError(f"Draw {row['id']} must contain {K} unique numbers")
    if any(not isinstance(value, int) or not 1 <= value <= n for value in numbers):
        raise ValueError(f"Draw {row['id']} contains a number outside 1..{n}")
    result = np.zeros(n, dtype=np.float64)
    result[np.asarray(numbers, dtype=np.int64) - 1] = 1
    return result


def _new_model(n):
    return OnlineModel(n)


def _model_config(game, model, selection_count, warmup):
    return {
        "model_version": MODEL_VERSION,
        "game": game,
        "number_count": model.n,
        "numbers_per_draw": K,
        "base_probability": model.base,
        "warmup_draws": warmup,
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
            model TEXT NOT NULL,
            predicted_at TEXT NOT NULL,
            probabilities_json TEXT NOT NULL,
            picks_json TEXT NOT NULL,
            dataset_version TEXT NOT NULL,
            config_json TEXT NOT NULL,
            actual_json TEXT,
            PRIMARY KEY (draw_id, model)
        );
        CREATE TABLE IF NOT EXISTS backtest_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            processed INTEGER NOT NULL,
            last_draw_id TEXT,
            data_version TEXT NOT NULL,
            warmup INTEGER NOT NULL,
            models_json TEXT NOT NULL
        );
        """
    )
    return conn


def _init_state(conn, n, warmup):
    result = conn.execute(
        "SELECT processed, last_draw_id, data_version, warmup, models_json "
        "FROM backtest_state WHERE singleton = 1"
    ).fetchone()
    if result is None:
        model = _new_model(n)
        conn.execute(
            "INSERT INTO backtest_state VALUES (1, 0, NULL, '', ?, ?)",
            (warmup, json.dumps(model.to_dict())),
        )
        conn.commit()
        return 0, None, "", model

    processed, last_draw_id, data_version, saved_warmup, models_json = result
    if saved_warmup != warmup:
        raise ValueError(
            "Backtest warm-up configuration changed; use a new backtest database"
        )
    model = OnlineModel.from_dict(json.loads(models_json))
    if model.n != n:
        raise ValueError("Backtest game size changed; use a new backtest database")
    return processed, last_draw_id, data_version, model


def _restore_features(rows, processed, n):
    builder = FeatureBuilder(n)
    digest = hashlib.sha256()
    for row in rows[:processed]:
        builder.observe(_outcome(row, n))
        digest.update(_canonical_row(row))
        digest.update(b"\n")
    return builder, digest


def _save_forecasts(
    conn, game, row, forecasts, dataset_version, selection_count, warmup
):
    draw_id = str(row["id"])
    existing = conn.execute(
        "SELECT model, probabilities_json FROM predictions "
        "WHERE draw_id = ? ORDER BY model",
        (draw_id,),
    ).fetchall()
    if existing:
        if {record[0] for record in existing} != set(MODEL_NAMES):
            raise RuntimeError(f"Incomplete saved backtest forecasts for draw {draw_id}")
        return {
            model: np.asarray(json.loads(probabilities), dtype=np.float64)
            for model, probabilities in existing
        }

    predicted_at = datetime.now(timezone.utc).isoformat()
    config = _model_config(game, _new_model(len(next(iter(forecasts.values())))),
                           selection_count, warmup)
    records = []
    for model_name in MODEL_NAMES:
        probabilities = forecasts[model_name]
        picks = (np.argsort(-probabilities, kind="stable")[:K] + 1).tolist()
        records.append(
            (
                draw_id,
                str(row["date"]),
                model_name,
                predicted_at,
                json.dumps(probabilities.tolist(), separators=(",", ":")),
                json.dumps(picks, separators=(",", ":")),
                dataset_version,
                json.dumps(config, separators=(",", ":")),
                None,
            )
        )
    with conn:
        conn.executemany(
            "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
    return forecasts


def _score_metric(probabilities, actual):
    p = np.clip(probabilities, METRIC_EPSILON, 1 - METRIC_EPSILON)
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
    return [
        float(value)
        for value in np.quantile(means, [tail, 1 - tail])
    ]


def summarize(conn):
    records = conn.execute(
        "SELECT draw_id, draw_date, model, probabilities_json, actual_json "
        "FROM predictions WHERE actual_json IS NOT NULL "
        "ORDER BY draw_date, draw_id, model"
    ).fetchall()
    ordered_draw_ids = list(dict.fromkeys(record[0] for record in records))
    draw_ids = set(ordered_draw_ids)
    model_draws = {model: set() for model in MODEL_NAMES}
    totals = {
        model: {"log_loss": 0.0, "brier_score": 0.0, "top_six_hits": 0}
        for model in MODEL_NAMES
    }
    draw_scores = {
        draw_id: {model: {"log_loss": None, "brier_score": None} for model in MODEL_NAMES}
        for draw_id in draw_ids
    }
    actual_by_draw = {}
    for draw_id, _, model, probabilities_json, actual_json in records:
        actual = np.asarray(json.loads(actual_json), dtype=np.float64)
        previous = actual_by_draw.setdefault(draw_id, actual)
        if not np.array_equal(previous, actual):
            raise RuntimeError(f"Inconsistent actual result for draw {draw_id}")
        probabilities = np.asarray(json.loads(probabilities_json), dtype=np.float64)
        log_loss, brier = _score_metric(probabilities, actual)
        totals[model]["log_loss"] += log_loss
        totals[model]["brier_score"] += brier
        draw_scores[draw_id][model]["log_loss"] = log_loss
        draw_scores[draw_id][model]["brier_score"] = brier
        picks = np.argsort(-probabilities, kind="stable")[:K]
        totals[model]["top_six_hits"] += int(actual[picks].sum())
        model_draws[model].add(draw_id)

    if any(draws != draw_ids for draws in model_draws.values()):
        raise RuntimeError("Models are not evaluated on a common draw set")
    count = len(draw_ids)
    models = {}
    for model in MODEL_NAMES:
        models[model] = {
            "draws": count,
            "log_loss": totals[model]["log_loss"] / count if count else None,
            "brier_score": totals[model]["brier_score"] / count if count else None,
            "top_six_hits_per_draw": (
                totals[model]["top_six_hits"] / count if count else None
            ),
        }
        if model != "base" and count:
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
            models[model]["log_loss_delta_vs_base"] = float(
                np.mean(log_loss_differences)
            )
            models[model]["log_loss_delta_95_ci_vs_base"] = _paired_block_interval(
                log_loss_differences, len(MODEL_NAMES) - 1
            )
            models[model]["brier_delta_vs_base"] = float(
                np.mean(brier_differences)
            )
            models[model]["brier_delta_95_ci_vs_base"] = _paired_block_interval(
                brier_differences, len(MODEL_NAMES) - 1
            )
        else:
            models[model]["log_loss_delta_vs_base"] = 0.0 if count else None
            models[model]["log_loss_delta_95_ci_vs_base"] = (
                [0.0, 0.0] if count > 1 else None
            )
            models[model]["brier_delta_vs_base"] = 0.0 if count else None
            models[model]["brier_delta_95_ci_vs_base"] = (
                [0.0, 0.0] if count > 1 else None
            )
    return {
        "draws": count,
        "models": models,
        "log_loss_definition": (
            "binary cross-entropy nats averaged over all numbers per draw, "
            "then averaged over draws"
        ),
        "brier_definition": (
            "binary Brier score averaged over all numbers per draw, "
            "then averaged over draws"
        ),
        "top_six_definition": (
            "mean count of actual main numbers in each model's six highest "
            "marginal probabilities; theoretical expectation is 36/n"
        ),
        "confidence_interval_definition": (
            "paired circular moving-block bootstrap 95% intervals versus base; "
            "block length sqrt(draws), 1,000 resamples, Bonferroni-adjusted "
            "for six model comparisons; exploratory, not a final untouched holdout"
        ),
    }


def run_walk_forward(rows, game, n, database_path, warmup=START):
    """Forecast each scored draw from its prefix, persist it, then observe the draw."""
    ordered = ordered_rows(rows)
    if warmup < 1:
        raise ValueError("warmup must be at least one draw")
    if n <= K:
        raise ValueError(f"Game size must exceed {K}, got {n}")

    conn = _database(database_path)
    try:
        processed, last_draw_id, saved_version, model = _init_state(conn, n, warmup)
        if processed > len(ordered):
            raise RuntimeError("History is shorter than the committed backtest checkpoint")
        if processed and str(ordered[processed - 1]["id"]) != last_draw_id:
            raise RuntimeError("Historical draw order changed; refusing to replay forecasts")
        builder, digest = _restore_features(ordered, processed, n)
        if processed and digest.hexdigest() != saved_version:
            raise RuntimeError("Processed historical data changed; refusing to rescore forecasts")

        for index in range(processed, len(ordered)):
            row = ordered[index]
            features = builder.current()
            if index >= warmup:
                forecasts = model.forecast(features)
                saved_forecasts = _save_forecasts(
                    conn,
                    game,
                    row,
                    forecasts,
                    digest.hexdigest(),
                    K,
                    warmup,
                )

            outcome = _outcome(row, n)
            if index >= warmup:
                actual_json = json.dumps(outcome.tolist(), separators=(",", ":"))
                with conn:
                    conn.execute(
                        "UPDATE predictions SET actual_json = ? "
                        "WHERE draw_id = ?",
                        (actual_json, str(row["id"])),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0] != len(MODEL_NAMES):
                        raise RuntimeError(f"Could not score forecasts for draw {row['id']}")
                model.observe(features, outcome, saved_forecasts)
            else:
                model.observe(features, outcome, model.forecast(features))

            builder.observe(outcome)
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
                        json.dumps(model.to_dict()),
                    ),
                )

        return {
            "processed_draws": processed,
            "warmup_draws": min(processed, warmup),
            "scored_draws": max(len(ordered) - warmup, 0),
            "first_draw": ordered[0]["date"],
            "last_draw": ordered[-1]["date"],
            "metrics": summarize(conn),
            "database_path": str(database_path),
        }
    finally:
        conn.close()
