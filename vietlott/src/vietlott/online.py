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


def _logloss(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).sum())


def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


class OnlineModel:
    F = N_FEATURES

    def __init__(self, n):
        self.n = n
        self.base = K / n
        self.names = ["base"] + [f"ewma_{d}" for d in DECAYS] + ["sgd"]
        self.ewma = {d: np.full(n, self.base) for d in DECAYS}
        self.w = np.zeros(self.F)
        self.b = math.log(self.base / (1 - self.base))
        self.logw = np.zeros(len(self.names))
        self.s1, self.s2, self.cnt = np.zeros(self.F), np.zeros(self.F), 0
        self.cum = {nm: 0.0 for nm in self.names + ["hedge"]}
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

    def predict(self, Xt):
        preds, _ = self.experts(Xt)
        return np.clip(sum(wi * pi for wi, pi in zip(self.weights(), preds)), EPS, 1 - EPS)

    def step(self, Xt, y):
        """Học 1 kỳ: chấm điểm trước, cập nhật sau."""
        preds, Z = self.experts(Xt)
        p_mix = np.clip(sum(wi * pi for wi, pi in zip(self.weights(), preds)), EPS, 1 - EPS)
        if self.processed >= START:
            for nm, pr in zip(self.names, preds):
                self.cum[nm] += _logloss(pr, y)
            self.cum["hedge"] += _logloss(p_mix, y)
            self.hits += int(y[np.argsort(-p_mix)[:K]].sum())
            self.scored += 1
        for i, pr in enumerate(preds):
            self.logw[i] -= ETA * _logloss(pr, y) / self.n
        for d in DECAYS:
            self.ewma[d] = d * self.ewma[d] + (1 - d) * y
        if self.cnt >= 50:
            g = _sigmoid(Z @ self.w + self.b) - y
            self.w -= LR * (Z.T @ g / self.n + L2 * self.w)
            self.b -= LR * g.mean()
        self.s1 += Xt.mean(0); self.s2 += (Xt ** 2).mean(0); self.cnt += 1
        self.processed += 1

    def to_dict(self):
        return {
            "n": self.n, "ewma": {str(d): v.tolist() for d, v in self.ewma.items()},
            "w": self.w.tolist(), "b": self.b, "logw": self.logw.tolist(),
            "s1": self.s1.tolist(), "s2": self.s2.tolist(), "cnt": self.cnt,
            "cum": self.cum, "hits": self.hits, "scored": self.scored,
            "processed": self.processed,
        }

    @classmethod
    def from_dict(cls, d):
        m = cls(d["n"])
        m.ewma = {float(k): np.array(v) for k, v in d["ewma"].items()}
        m.w, m.b = np.array(d["w"]), d["b"]
        m.logw = np.array(d["logw"])
        m.s1, m.s2, m.cnt = np.array(d["s1"]), np.array(d["s2"]), d["cnt"]
        m.cum, m.hits, m.scored, m.processed = d["cum"], d["hits"], d["scored"], d["processed"]
        return m
