"""Đặc trưng cho từng số tại mỗi kỳ - chỉ dùng dữ liệu TRƯỚC kỳ đó."""
from collections import deque

import numpy as np

WINDOWS = (5, 10, 30, 100, 300)
N_FEATURES = len(WINDOWS) + 2


class FeatureBuilder:
    """Build number features from draws observed strictly before the next draw."""

    def __init__(self, n):
        self.n = n
        self.processed = 0
        self.history = deque(maxlen=max(WINDOWS))
        self.window_sums = {
            window: np.zeros(n, dtype=np.float64) for window in WINDOWS
        }
        self.last_seen = np.full(n, -1, dtype=np.int64)
        self.position = np.arange(n, dtype=np.float64) / n

    def current(self):
        features = []
        for window in WINDOWS:
            count = min(self.processed, window)
            features.append(self.window_sums[window] / max(count, 1))
        gap = np.where(
            self.last_seen < 0,
            self.processed + 1,
            self.processed - self.last_seen,
        )
        features.extend((gap, self.position))
        return np.stack(features, axis=1).astype(np.float32)

    def observe(self, outcome):
        outcome = np.asarray(outcome, dtype=np.float64)
        if outcome.shape != (self.n,):
            raise ValueError(f"Expected outcome shape {(self.n,)}, got {outcome.shape}")
        if not np.all((outcome == 0) | (outcome == 1)):
            raise ValueError("Draw outcomes must be binary")

        for window in WINDOWS:
            if len(self.history) >= window:
                self.window_sums[window] -= self.history[-window]
            self.window_sums[window] += outcome
        self.last_seen = np.where(outcome == 1, self.processed, self.last_seen)
        self.history.append(outcome.copy())
        self.processed += 1


def build_features(M):
    """X[t, i, f]: rolling frequencies, absence gap, and number position."""
    M = np.asarray(M)
    if M.ndim != 2:
        raise ValueError("Expected a two-dimensional outcome matrix")
    builder = FeatureBuilder(M.shape[1])
    features = np.empty((len(M), M.shape[1], N_FEATURES), dtype=np.float32)
    for index, outcome in enumerate(M):
        features[index] = builder.current()
        builder.observe(outcome)
    return features
