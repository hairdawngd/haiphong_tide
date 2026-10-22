"""Lõi: học kỳ mới, đối chiếu số đã dự đoán với kết quả, tạo dự đoán cho kỳ sau."""
import json
import os
from collections import Counter
from pathlib import Path

import numpy as np

from .data import N_NUMBERS, to_matrices
from .features import build_features
from .model import OnlineModel
from .stats import P_LOTO, P_SPECIAL

HISTORY_KEEP = 200


def home():
    p = Path(os.environ.get("XSMB_HOME", "/data"))
    p.mkdir(parents=True, exist_ok=True)
    return p


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
    return {"draws": 0, "loto_picks": 0, "loto_hits": 0, "loto_times": 0,
            "special_picks": 0, "special_hits": 0, "since": None}


def load_log():
    log = _read(home() / "log.json", None)
    return log or {"pending": None, "history": [], "stats": empty_stats()}


def evaluate(pending, row):
    """Đối chiếu từng số đã dự đoán với kết quả thật; ghi rõ ra ở giải nào."""
    cnt = Counter(row["loto"])
    loto = []
    for n in pending["loto"]:
        where = [label for label, vals in row["prizes"].items()
                 if any(int(v[-2:]) == n for v in vals)]
        loto.append({"number": n, "times": cnt.get(n, 0), "classes": where})
    special = [{"number": n, "hit": n == row["special"]} for n in pending["special"]]
    return {"draw_id": row["id"], "date": row["date"], "prizes": row["prizes"],
            "special_two": row["special"], "loto": loto, "special": special}


def _apply_stats(st, ev):
    st["draws"] += 1
    st["since"] = st["since"] or ev["date"]
    for r in ev["loto"]:
        st["loto_picks"] += 1
        st["loto_hits"] += 1 if r["times"] else 0
        st["loto_times"] += r["times"]
    for r in ev["special"]:
        st["special_picks"] += 1
        st["special_hits"] += 1 if r["hit"] else 0


def _top(p, k):
    return sorted(int(i) for i in np.argsort(-p)[:k])


def update(rows, loto_count, special_count):
    h = home()
    N = len(rows)
    ids = [r["id"] for r in rows]
    lo_saved, sp_saved = _read(h / "loto_model.json", None), _read(h / "special_model.json", None)
    first_run = lo_saved is None or sp_saved is None
    m_lo = OnlineModel.from_dict(lo_saved) if lo_saved else OnlineModel(N_NUMBERS, P_LOTO)
    m_sp = OnlineModel.from_dict(sp_saved) if sp_saved else OnlineModel(N_NUMBERS, P_SPECIAL)
    if m_lo.processed > N or m_sp.processed > N:
        m_lo, m_sp, first_run = OnlineModel(N_NUMBERS, P_LOTO), OnlineModel(N_NUMBERS, P_SPECIAL), True

    log = load_log()
    pend = log.get("pending")

    def result(events):
        return {"events": events, "first_run": first_run, "pending": log["pending"],
                "stats": log["stats"], "latest": rows[-1]}

    # không có kỳ mới -> không cần tính lại (tiết kiệm CPU trên thiết bị nhỏ)
    if (not first_run and m_lo.processed == N and m_sp.processed == N
            and pend and pend["after_id"] == ids[-1]):
        return result([])

    events = []
    if pend and pend["after_id"] in ids:
        pos = ids.index(pend["after_id"]) + 1
        if pos < N:
            ev = evaluate(pend, rows[pos])
            _apply_stats(log["stats"], ev)
            log["history"] = (log["history"] + [ev])[-HISTORY_KEEP:]
            events.append(ev)

    M_lo, M_sp = to_matrices(rows)
    X_lo, X_sp = build_features(M_lo), build_features(M_sp)
    for t in range(m_lo.processed, N):
        m_lo.step(X_lo[t], M_lo[t])
    for t in range(m_sp.processed, N):
        m_sp.step(X_sp[t], M_sp[t])
    _write(h / "loto_model.json", m_lo.to_dict())
    _write(h / "special_model.json", m_sp.to_dict())

    if not pend or pend["after_id"] != ids[-1] or events:
        nxt_lo = build_features(np.vstack([M_lo, np.zeros((1, N_NUMBERS))]))[-1]
        nxt_sp = build_features(np.vstack([M_sp, np.zeros((1, N_NUMBERS))]))[-1]
        p_lo, p_sp = m_lo.predict(nxt_lo), m_sp.predict(nxt_sp)
        log["pending"] = {
            "after_id": ids[-1], "after_date": rows[-1]["date"],
            "loto": _top(p_lo, loto_count), "special": _top(p_sp, special_count),
            "loto_probs": {str(int(i)): round(float(p_lo[i]), 4) for i in np.argsort(-p_lo)[:10]},
            "special_probs": {str(int(i)): round(float(p_sp[i]), 5) for i in np.argsort(-p_sp)[:10]},
            "loto_base": round(P_LOTO, 4), "special_base": P_SPECIAL}
    _write(h / "log.json", log)
    return result(events)
