"""Tải và làm sạch dữ liệu Vietlott (giữ cả số phụ của Power 6/55)."""
import json

import numpy as np
import requests

K = 6
BASE_URL = "https://raw.githubusercontent.com/vietvudanh/vietlott-data/master/data/"
SOURCES = {
    "mega645": (BASE_URL + "power645.jsonl", 45),
    "power655": (BASE_URL + "power655.jsonl", 55),
}


def load(game):
    """Trả về (danh sách kỳ đã sắp xếp theo thời gian, số lớn nhất).

    Mỗi kỳ: {"date", "id", "numbers": [6 số đã sắp xếp], "bonus": số phụ hoặc None}
    """
    url, n_max = SOURCES[game]
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    rows = {}
    for line in resp.text.splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            result = r.get("result", [])
            main = result[:K]
            if (
                len(main) == K
                and len(set(main)) == K
                and all(isinstance(x, int) and 1 <= x <= n_max for x in main)
            ):
                bonus = result[K] if len(result) > K and isinstance(result[K], int) else None
                rows[str(r.get("id", ""))] = {
                    "date": str(r.get("date", "")),
                    "id": str(r.get("id", "")),
                    "numbers": sorted(main),
                    "bonus": bonus,
                }
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
    if not rows:
        raise RuntimeError("Không có dữ liệu hợp lệ; kiểm tra URL/cấu trúc JSONL.")
    out = sorted(rows.values(), key=lambda r: (r["date"], r["id"]))
    return out, n_max


def to_matrix(rows, n):
    """Ma trận nhị phân (số kỳ x n): số nào xuất hiện ở kỳ nào."""
    M = np.zeros((len(rows), n))
    for t, r in enumerate(rows):
        M[t, [x - 1 for x in r["numbers"]]] = 1
    return M
