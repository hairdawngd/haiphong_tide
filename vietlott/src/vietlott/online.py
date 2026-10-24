"""Mô hình học trực tuyến: base, 3 EWMA, SGD logistic và Hedge tổ hợp.

Mỗi kỳ: chấm điểm dự đoán TRƯỚC, rồi mới cập nhật. Có thể lưu/nạp trạng thái.
"""
import math

import numpy as np

from .data import K
from .features import N_FEATURES

EPS = 1e-6
DECAYS = (0.99, 0.995, 0.999)
START = 100
LR, L2, ETA = 0.002, 1e-2, 0.5
MODEL_VERSION = 4


def _logloss(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return float(-(y * np.log(p) + (1 - y) * np.log1p(-p)).mean())


def _brier_score(p, y):
    return float(((p - y) ** 2).mean())


def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


class OnlineModel:
    F = N_FEATURES

    def __init__(self, n):
        self.n = n
        self.base = K / n
        self.names = ["base"] + [f"ewma_{d}" for d in DECAYS] + ["sgd"]
        self.ewma = {d: np.full(n, self.base) for d in DECAYS}
        self.counts = np.zeros(n, dtype=np.float64)
        self.w = np.zeros(self.F)
        self.b = math.log(self.base / (1 - self.base))
        self.logw = np.zeros(len(self.names))
        self.s1, self.s2, self.cnt = np.zeros(self.F), np.zeros(self.F), 0
        self.cum = {nm: 0.0 for nm in self.names + ["hedge"]}
        self.cum_brier = {nm: 0.0 for nm in self.names + ["hedge"]}
        self.hits, self.scored, self.processed = 0, 0, 0

    def _norm(self):
        if self.cnt == 0:
            return np.zeros(self.F), np.ones(self.F)
        mu = self.s1 / self.cnt
        return mu, np.sqrt(np.maximum(self.s2 / self.cnt - mu ** 2, 1e-12))

    def experts(self, Xt):
        mu, sd = self._norm()
        Z = np.clip((Xt - mu) / sd, -4, 4)
        preds = [np.full(self.n, self.base)]
        preds += [self.base + 0.5 * (self.ewma[d] - self.base) for d in DECAYS]
        preds.append(_sigmoid(Z @ self.w + self.b))
        return preds, Z

    def weights(self):
        w = np.exp(self.logw - self.logw.max())
        return w / w.sum()

    def forecast(self, Xt):
        preds, _ = self.experts(Xt)
        forecasts = dict(zip(self.names, [
            np.clip(pred, EPS, 1 - EPS) for pred in preds
        ]))
        forecasts["beta_binomial"] = np.clip(
            (self.counts + self.base * self.n) / (self.n + self.processed),
            EPS,
            1 - EPS,
        )
        forecasts["hedge"] = np.clip(
            sum(wi * pi for wi, pi in zip(self.weights(), preds)), EPS, 1 - EPS
        )
        return forecasts

    def predict(self, Xt):
        return self.forecast(Xt)["hedge"]

    def observe(self, Xt, y, forecasts):
        """Score an already issued forecast, then update experts and Hedge weights."""
        y = np.asarray(y, dtype=np.float64)
        if y.shape != (self.n,):
            raise ValueError(f"Expected label shape {(self.n,)}, got {y.shape}")
        _, Z = self.experts(Xt)
        losses = {
            name: _logloss(forecasts[name], y)
            for name in self.names
        }
        hedge_loss = _logloss(forecasts["hedge"], y)
        if self.processed >= START:
            for name in self.names:
                self.cum[name] += losses[name]
                self.cum_brier[name] += _brier_score(forecasts[name], y)
            self.cum["hedge"] += hedge_loss
            self.cum_brier["hedge"] += _brier_score(forecasts["hedge"], y)
            self.hits += int(y[np.argsort(-forecasts["hedge"])[:K]].sum())
            self.scored += 1
        for i, name in enumerate(self.names):
            self.logw[i] -= ETA * losses[name]
        for d in DECAYS:
            self.ewma[d] = d * self.ewma[d] + (1 - d) * y
        self.counts += y
        if self.cnt >= 50:
            g = _sigmoid(Z @ self.w + self.b) - y
            self.w -= LR * (Z.T @ g / self.n + L2 * self.w)
            self.b -= LR * g.mean()
        self.s1 += Xt.mean(0)
        self.s2 += (Xt ** 2).mean(0)
        self.cnt += 1
        self.processed += 1

    def step(self, Xt, y):
        """Compatibility helper: forecast before observing the draw."""
        forecasts = self.forecast(Xt)
        self.observe(Xt, y, forecasts)
        return forecasts

    def to_dict(self):
        return {
            "model_version": MODEL_VERSION,
            "n": self.n, "ewma": {str(d): v.tolist() for d, v in self.ewma.items()},
            "counts": self.counts.tolist(),
            "w": self.w.tolist(), "b": self.b, "logw": self.logw.tolist(),
            "s1": self.s1.tolist(), "s2": self.s2.tolist(), "cnt": self.cnt,
            "cum": self.cum, "cum_brier": self.cum_brier,
            "hits": self.hits, "scored": self.scored,
            "processed": self.processed,
        }

    @classmethod
    def from_dict(cls, d):
        if d.get("model_version") != MODEL_VERSION:
            raise ValueError("Unsupported serialized model version")
        m = cls(d["n"])
        m.ewma = {float(k): np.array(v) for k, v in d["ewma"].items()}
        m.counts = np.array(d["counts"], dtype=np.float64)
        m.w, m.b = np.array(d["w"]), d["b"]
        m.logw = np.array(d["logw"])
        m.s1, m.s2, m.cnt = np.array(d["s1"]), np.array(d["s2"]), d["cnt"]
        m.cum, m.cum_brier = d["cum"], d["cum_brier"]
        m.hits, m.scored, m.processed = d["hits"], d["scored"], d["processed"]
        return m
