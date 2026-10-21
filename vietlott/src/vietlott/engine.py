"""Lõi: học kỳ mới, chấm điểm các bộ số đã dự đoán, tạo dự đoán cho kỳ tiếp theo."""
import json
import os
from pathlib import Path

import numpy as np

from . import prizes
from .data import K, to_matrix
from .features import build_features
from .online import OnlineModel

HISTORY_KEEP = 200


def home():
    p = Path(os.environ.get("VIETLOTT_HOME", "/data"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _paths(game):
    h = home()
    return h / f"{game}_model.json", h / f"{game}_log.json"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def empty_stats():
    return {"draws": 0, "sets": 0, "wins": 0, "match_hist": {str(i): 0 for i in range(7)},
            "tiers": {}, "prize_total": 0, "since": None}


def load_log(game):
    log = _read(_paths(game)[1], None)
    if not log:
        log = {"pending": None, "history": [], "stats": empty_stats()}
    return log


def evaluate(game, pending, row):
    """Đối chiếu từng bộ số đã dự đoán với kết quả thật của kỳ."""
    main, bonus = set(row["numbers"]), row.get("bonus")
    sets = []
    for s in pending["sets"]:
        m = len(main & set(s))
        bonus_hit = bool(bonus is not None and bonus in s)
        tier = prizes.classify(game, m, bonus_hit)
        sets.append({"numbers": s, "matches": m, "bonus_hit": bonus_hit, "tier": tier,
                     "prize": prizes.tier_value(game, tier) if tier else 0})
    return {"game": game, "draw_id": row["id"], "date": row["date"], "numbers": row["numbers"],
            "bonus": bonus, "sets": sets, "prize": sum(x["prize"] for x in sets)}


def _apply_stats(stats, ev):
    stats["draws"] += 1
    stats["since"] = stats["since"] or ev["date"]
    for s in ev["sets"]:
        stats["sets"] += 1
        stats["match_hist"][str(s["matches"])] += 1
        if s["tier"]:
            stats["wins"] += 1
            stats["tiers"][s["tier"]] = stats["tiers"].get(s["tier"], 0) + 1
            stats["prize_total"] += s["prize"]


def make_sets(p_next, count, seed):
    """Bộ 1 = top-6 theo mô hình; các bộ còn lại lấy mẫu có trọng số theo xác suất mô hình."""
    order = np.argsort(-p_next)
    sets = [sorted(int(i) + 1 for i in order[:K])]
    rng = np.random.default_rng(seed)
    probs = p_next / p_next.sum()
    for _ in range(500):
        if len(sets) >= count:
            break
        pick = rng.choice(len(p_next), size=K, replace=False, p=probs)
        s = sorted(int(i) + 1 for i in pick)
        if s not in sets:
            sets.append(s)
    return sets


def update(game, rows, n, sets_per_draw):
    """Học kỳ mới -> chấm điểm dự đoán cũ -> tạo dự đoán mới. Trả về dict kết quả."""
    mpath, lpath = _paths(game)
    N = len(rows)
    ids = [r["id"] for r in rows]
    M = to_matrix(rows, n)
    X = build_features(M)

    saved = _read(mpath, None)
    model = OnlineModel.from_dict(saved) if saved else OnlineModel(n)
    if model.n != n or model.processed > N:
        model = OnlineModel(n)
    first_run = saved is None

    log = load_log(game)
    events = []

    pend = log.get("pending")
    if pend and pend["after_id"] in ids:
        pos = ids.index(pend["after_id"]) + 1
        if pos < N:  # kỳ ngay sau thời điểm dự đoán đã có kết quả
            ev = evaluate(game, pend, rows[pos])
            _apply_stats(log["stats"], ev)
            log["history"].append(ev)
            log["history"] = log["history"][-HISTORY_KEEP:]
            events.append(ev)

    for t in range(model.processed, N):
        model.step(X[t], M[t])
    _write(mpath, model.to_dict())

    pend = log.get("pending")
    if not pend or pend["after_id"] != ids[-1] or events:
        Xn = build_features(np.vstack([M, np.zeros((1, n))]))[-1]
        p_next = model.predict(Xn)
        seed = int(ids[-1]) if ids[-1].isdigit() else N
        order = np.argsort(-p_next)
        log["pending"] = {
            "after_id": ids[-1], "after_date": rows[-1]["date"],
            "sets": make_sets(p_next, sets_per_draw, seed),
            "top_probs": {str(int(i) + 1): round(float(p_next[i]), 5) for i in order[:10]},
            "base": round(model.base, 5),
        }
    _write(lpath, log)
    return {"events": events, "first_run": first_run, "pending": log["pending"],
            "stats": log["stats"], "latest": rows[-1], "model": model}
