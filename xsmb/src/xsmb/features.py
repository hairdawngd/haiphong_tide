"""Đặc trưng cho từng số tại mỗi kỳ - chỉ dùng dữ liệu TRƯỚC kỳ đó."""
import numpy as np

WINDOWS = (5, 10, 30, 100, 300)
N_FEATURES = len(WINDOWS) + 2


def build_features(M):
    N, n = M.shape
    cs = np.vstack([np.zeros((1, n)), np.cumsum(M, axis=0)])
    idx = np.arange(N)
    feats = []
    for w in WINDOWS:
        lo = np.maximum(idx - w, 0)
        feats.append((cs[idx] - cs[lo]) / np.maximum(idx - lo, 1)[:, None])
    gap = np.zeros((N, n))
    last = np.full(n, -1.0)
    for t in range(N):
        gap[t] = np.where(last < 0, t + 1, t - last)
        last = np.where(M[t] == 1, t, last)
    feats.append(gap)
    feats.append(np.tile(np.arange(n), (N, 1)) / n)
    return np.stack(feats, axis=2).astype(np.float32)
