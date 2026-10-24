"""Đặc trưng nhân quả; ``current`` chỉ dùng các hàng đã đưa vào ``observe``."""
from collections import deque

import numpy as np

WINDOWS = (5, 10, 30, 100, 300)
N_FEATURES = len(WINDOWS) + 2


class FeatureBuilder:
    """Build per-number features from outcomes observed strictly before a draw."""

    def __init__(self, n):
        self.n = n
        self.processed = 0
        self.history = deque(maxlen=max(WINDOWS))
        self.window_sums = {window: np.zeros(n, dtype=np.float64) for window in WINDOWS}
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

        for window in WINDOWS:
            if len(self.history) >= window:
                self.window_sums[window] -= self.history[-window]
            self.window_sums[window] += outcome
        self.last_seen = np.where(outcome == 1, self.processed, self.last_seen)
        self.history.append(outcome.copy())
        self.processed += 1


def build_features(M):
    M = np.asarray(M)
    if M.ndim != 2:
        raise ValueError("Expected a two-dimensional outcome matrix")
    builder = FeatureBuilder(M.shape[1])
    features = np.empty((len(M), M.shape[1], N_FEATURES), dtype=np.float32)
    for t, outcome in enumerate(M):
        features[t] = builder.current()
        builder.observe(outcome)
    return features
