#!/usr/bin/env python3
"""
calibration — optional logistic calibration of the judge's suspicion.

The judge (auditor.py) returns a 0-10 score per dimension; ira.py turns each into
a suspicion probability p that feeds the noisy-OR. By default that map is the
hand-set identity p = score/10. This module lets it be *calibrated* from labelled
data: a one-feature logistic per dimension, p = sigmoid(a·x + b) with x = score/10,
fitted class-balanced with L2.

Design choices, on purpose:
  • Per dimension, 1-2 parameters — survives few labels where learning the whole
    verdict would overfit.
  • A dimension is only calibrated when it had enough examples of BOTH classes
    (MIN_TOTAL / MIN_PER_CLASS); otherwise it stays identity. No model on disk
    ⇒ every dimension is identity ⇒ the IRA behaves exactly as before.
  • Only the soft judge probabilities pass through here. Hard floors, the impact
    axis and the session escalation never touch calibration (fail-closed intact).

Fitting needs a dataset of judge scores with a malicious/safe label, e.g.
  [{"dims": {"constraint_adherence": 8, "goal_alignment": 3, ...}, "label": 1}, ...]
produced by running the judge over the labelled fixtures. Then:
  python calibration.py fit dataset.json
  python calibration.py show
"""
from __future__ import annotations
import json
import math
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(ROOT, "calibration.json")

# A dimension is calibrated only with enough signal; below this it stays identity.
MIN_TOTAL = 8
MIN_PER_CLASS = 3


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _fit_1d(xs: list[float], ys: list[int], l2: float = 1.0,
            epochs: int = 2000, lr: float = 0.3) -> tuple[float, float]:
    """One-feature logistic regression p = sigmoid(a·x + b) by gradient descent,
    class-balanced so a handful of positives are not swamped by the negatives."""
    n = len(xs)
    pos = sum(ys) or 1
    neg = (n - sum(ys)) or 1
    wpos, wneg = n / (2 * pos), n / (2 * neg)
    a, b = 0.0, 0.0
    for _ in range(epochs):
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            p = _sigmoid(a * x + b)
            wt = wpos if y else wneg
            g = wt * (p - y)
            ga += g * x
            gb += g
        a -= lr * (ga / n + l2 * a / n)
        b -= lr * (gb / n)
    return a, b


class Calibrator:
    def __init__(self, params: dict[str, tuple[float, float]] | None = None):
        self.params = params or {}

    def calibrate(self, dim: str, x01: float) -> float:
        """Calibrated p for one judge dimension; identity when the dim has no model."""
        ab = self.params.get(dim)
        return _sigmoid(ab[0] * x01 + ab[1]) if ab else x01

    def fit(self, rows: list[dict], l2: float = 1.0) -> dict:
        """rows: [{"dims": {dim: score 0-10, ...}, "label": 0|1}, ...]."""
        by_dim: dict[str, tuple[list, list]] = {}
        for r in rows:
            y = int(r["label"])
            for dim, score in (r.get("dims") or {}).items():
                xs, ys = by_dim.setdefault(dim, ([], []))
                xs.append(float(score) / 10.0)
                ys.append(y)
        report, self.params = {}, {}
        for dim, (xs, ys) in by_dim.items():
            pos, neg = sum(ys), len(ys) - sum(ys)
            if len(xs) >= MIN_TOTAL and pos >= MIN_PER_CLASS and neg >= MIN_PER_CLASS:
                a, b = _fit_1d(xs, ys, l2)
                self.params[dim] = (a, b)
                report[dim] = {"calibrated": True, "n": len(xs), "pos": pos,
                               "a": round(a, 3), "b": round(b, 3)}
            else:
                report[dim] = {"calibrated": False, "n": len(xs), "pos": pos,
                               "reason": "too few examples of both classes -> identity"}
        return report

    def save(self, path: str = MODEL_PATH):
        json.dump({"params": {k: list(v) for k, v in self.params.items()}},
                  open(path, "w"), indent=2)

    @classmethod
    def load(cls, path: str = MODEL_PATH):
        if not os.path.exists(path):
            return cls({})
        d = json.load(open(path))
        return cls({k: tuple(v) for k, v in (d.get("params") or {}).items()})


_CAL: Calibrator | None = None


def _get() -> Calibrator:
    global _CAL
    if _CAL is None:
        _CAL = Calibrator.load()
    return _CAL


def calibrate(dim: str, x01: float) -> float:
    """Calibrated suspicion p for a judge dimension; identity if no model is trained."""
    return _get().calibrate(dim, x01)


def reload():
    global _CAL
    _CAL = None


def main():
    import argparse
    ap = argparse.ArgumentParser(description="logistic calibration of the judge's suspicion")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit", help="fit per-dimension calibration from a labelled JSON")
    f.add_argument("dataset", help='JSON list of {"dims": {dim: score 0-10}, "label": 0|1}')
    f.add_argument("--l2", type=float, default=1.0)
    f.add_argument("--out", default=MODEL_PATH)
    sub.add_parser("show", help="print the current calibration")
    a = ap.parse_args()
    if a.cmd == "fit":
        rows = json.load(open(a.dataset))
        c = Calibrator()
        rep = c.fit(rows, a.l2)
        c.save(a.out)
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        print(f"saved -> {a.out}")
    elif a.cmd == "show":
        c = Calibrator.load()
        if not c.params:
            print("no calibration model on disk — identity for every dimension")
        else:
            for dim, (aa, bb) in c.params.items():
                print(f"{dim:24} p = sigmoid({aa:.3f}·(score/10) + {bb:.3f})")


if __name__ == "__main__":
    main()
