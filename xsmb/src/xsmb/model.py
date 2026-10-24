"""Base, EWMA, logistic SGD và Hedge; forecast và observe được tách riêng."""
import math

import numpy as np

from .features import N_FEATURES

EPS = 1e-6
DECAYS = (0.99, 0.995, 0.999)
WARMUP_DRAWS = 100
LR, L2, ETA = 0.002, 1e-2, 0.5
MODEL_VERSION = 3


def _normalise(p):
    p = np.clip(p, EPS, None)
    return p / p.sum()


def _forecast_loss(p, y, categorical):
    p = np.clip(p, EPS, 1 - EPS)
    if categorical:
        return float(-(y * np.log(p)).sum())
    return float(-(y * np.log(p) + (1 - y) * np.log1p(-p)).mean())


def _brier_score(p, y, categorical):
    squared_error = (p - y) ** 2
    return float(squared_error.sum() if categorical else squared_error.mean())


def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


class OnlineModel:
    F = N_FEATURES

    def __init__(self, n, base, categorical=False, warmup=WARMUP_DRAWS):
        self.n, self.base = n, base
        self.categorical, self.warmup = categorical, warmup
        self.names = ["base"] + [f"ewma_{d}" for d in DECAYS] + ["sgd"]
        self.counts = np.zeros(n, dtype=np.float64)
        self.ewma = {d: np.full(n, base) for d in DECAYS}
        self.w = np.zeros(self.F)
        self.b = math.log(base / (1 - base))
        self.logw = np.zeros(len(self.names))
        self.s1, self.s2, self.cnt = np.zeros(self.F), np.zeros(self.F), 0
        self.cum = {nm: 0.0 for nm in self.names + ["hedge"]}
        self.cum_brier = {nm: 0.0 for nm in self.names + ["hedge"]}
        self.scored, self.processed = 0, 0

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
        if self.categorical:
            preds = [_normalise(pred) for pred in preds]
        else:
            preds = [np.clip(pred, EPS, 1 - EPS) for pred in preds]
        forecast = dict(zip(self.names, preds))
        if self.categorical:
            bayes = (self.counts + 1.0) / (self.processed + self.n)
        else:
            prior_successes = self.base * self.n
            bayes = (self.counts + prior_successes) / (self.processed + self.n)
        forecast["beta_binomial"] = _normalise(bayes) if self.categorical else np.clip(
            bayes, EPS, 1 - EPS
        )
        forecast["hedge"] = np.clip(
            sum(wi * pi for wi, pi in zip(self.weights(), preds)), EPS, 1 - EPS
        )
        if self.categorical:
            forecast["hedge"] = _normalise(forecast["hedge"])
        return forecast

    def predict(self, Xt):
        return self.forecast(Xt)["hedge"]

    def observe(self, Xt, y, forecasts):
        y = np.asarray(y, dtype=np.float64)
        if y.shape != (self.n,):
            raise ValueError(f"Expected label shape {(self.n,)}, got {y.shape}")
        _, Z = self.experts(Xt)
        losses = {
            name: _forecast_loss(forecasts[name], y, self.categorical)
            for name in self.names
        }
        hedge_loss = _forecast_loss(forecasts["hedge"], y, self.categorical)

        if self.processed >= self.warmup:
            for name in self.names:
                self.cum[name] += losses[name]
                self.cum_brier[name] += _brier_score(
                    forecasts[name], y, self.categorical
                )
            self.cum["hedge"] += hedge_loss
            self.cum_brier["hedge"] += _brier_score(
                forecasts["hedge"], y, self.categorical
            )
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
        self.s1 += Xt.mean(0); self.s2 += (Xt.astype(np.float64) ** 2).mean(0); self.cnt += 1
        self.processed += 1

    def step(self, Xt, y):
        """Compatibility helper: issue the forecast before observing its label."""
        forecasts = self.forecast(Xt)
        self.observe(Xt, y, forecasts)
        return forecasts

    def to_dict(self):
        return {"model_version": MODEL_VERSION, "n": self.n, "base": self.base,
                "categorical": self.categorical, "warmup": self.warmup,
                "ewma": {str(d): v.tolist() for d, v in self.ewma.items()},
                "counts": self.counts.tolist(),
                "w": self.w.tolist(), "b": self.b, "logw": self.logw.tolist(),
                "s1": self.s1.tolist(), "s2": self.s2.tolist(), "cnt": self.cnt,
                "cum": self.cum, "cum_brier": self.cum_brier,
                "scored": self.scored, "processed": self.processed}

    @classmethod
    def from_dict(cls, d):
        if d.get("model_version") != MODEL_VERSION:
            raise ValueError("Unsupported serialized model version")
        m = cls(
            d["n"], d["base"], d.get("categorical", False),
            d.get("warmup", WARMUP_DRAWS),
        )
        m.ewma = {float(k): np.array(v) for k, v in d["ewma"].items()}
        m.counts = np.array(d["counts"], dtype=np.float64)
        m.w, m.b, m.logw = np.array(d["w"]), d["b"], np.array(d["logw"])
        m.s1, m.s2, m.cnt = np.array(d["s1"]), np.array(d["s2"]), d["cnt"]
        m.cum = d["cum"]
        m.cum_brier = d["cum_brier"]
        m.scored, m.processed = d["scored"], d["processed"]
        return m
