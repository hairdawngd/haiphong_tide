"""Tải dữ liệu XSMB từ https://github.com/khiemdoan/vietnam-lottery-xsmb-analysis (MIT)."""
import csv
import io

import numpy as np
import requests

CSV_URL = ("https://raw.githubusercontent.com/khiemdoan/vietnam-lottery-xsmb-analysis/"
           "refs/heads/main/data/xsmb.csv")

# (tiền tố cột, nhãn, số giải, số chữ số)
CLASSES = [
    ("special", "ĐB", 1, 5), ("prize1", "G1", 1, 5), ("prize2", "G2", 2, 5),
    ("prize3", "G3", 6, 5), ("prize4", "G4", 4, 4), ("prize5", "G5", 6, 4),
    ("prize6", "G6", 3, 3), ("prize7", "G7", 4, 2),
]
N_NUMBERS = 100  # các số 00..99


def parse(text):
    rows = {}
    for r in csv.DictReader(io.StringIO(text)):
        try:
            date = r["date"].strip()[:10]
            prizes = {}
            for key, label, count, width in CLASSES:
                cols = [key] if count == 1 else [f"{key}_{i}" for i in range(1, count + 1)]
                vals = []
                for c in cols:
                    v = r[c].strip()
                    if not v.isdigit() or len(v) > width:
                        raise ValueError(c)
                    vals.append(v.zfill(width))  # CSV làm mất số 0 đứng đầu
                prizes[label] = vals
        except (KeyError, ValueError, AttributeError):
            continue
        loto = [int(v[-2:]) for vals in prizes.values() for v in vals]  # 27 số
        rows[date] = {"id": date, "date": date, "prizes": prizes, "loto": loto,
                      "special": int(prizes["ĐB"][0][-2:])}
    if not rows:
        raise RuntimeError("Không có dữ liệu hợp lệ; kiểm tra URL/cấu trúc CSV.")
    return [rows[k] for k in sorted(rows)]


def load():
    resp = requests.get(CSV_URL, timeout=60)
    resp.raise_for_status()
    return parse(resp.content.decode("utf-8"))


def to_matrices(rows):
    """(loto, special): ma trận nhị phân N x 100.

    loto[t, i] = 1 nếu số i xuất hiện ít nhất một lần trong 27 giải kỳ t;
    special[t, i] = 1 nếu i là 2 số cuối giải Đặc biệt kỳ t.
    """
    N = len(rows)
    lo, sp = np.zeros((N, N_NUMBERS)), np.zeros((N, N_NUMBERS))
    for t, r in enumerate(rows):
        lo[t, sorted(set(r["loto"]))] = 1
        sp[t, r["special"]] = 1
    return lo, sp
