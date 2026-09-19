#!/usr/bin/env python3
"""
ar_train — the predictive model over the guard's signal space. numpy only.

Logistic regression (L2, class-balanced) on the per-event features from
ar_dataset.py, predicting y = "this event deserves S2 or higher" (gate / contain).
Small and explainable on purpose: with hundreds of events the useful question is
"which signals carry weight, and where does the learned boundary beat the
hand-written one?", not "can a deep model memorise the fixtures?" — see
angryrobot/learn.py for the same argument.

  /usr/bin/python3 ar_train.py               # → data/model.json (+ report on dev/test)
  /usr/bin/python3 ar_train.py --l2 0.3 --epochs 3000

Reports precision / recall / AUC per split, recall per family, the guard's
rule baseline on the same rows, and the 12 heaviest weights.
"""
import argparse, collections, json, os
import numpy as np

DATA = os.path.join("data", "dataset.jsonl")
OUT = os.path.join("data", "model.json")


def load():
    rows = [json.loads(l) for l in open(DATA) if l.strip()]
    keys = sorted(rows[0]["features"])
    X = np.array([[r["features"][k] for k in keys] for r in rows], dtype=float)
    y = np.array([r["y"] for r in rows], dtype=float)
    return rows, keys, X, y


def fit(X, y, l2=0.1, epochs=2000, lr=0.1):
    n, d = X.shape
    w = np.zeros(d); b = 0.0
    pos = y.sum(); neg = n - pos
    cw = np.where(y == 1, n / (2 * max(pos, 1)), n / (2 * max(neg, 1)))       # balanced classes
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        g = cw * (p - y)
        w -= lr * ((X.T @ g) / n + l2 * w / n); b -= lr * g.mean()
    return w, b


def auc(scores, y):
    if y.sum() == 0 or y.sum() == len(y): return None
    order = np.argsort(scores); ranks = np.empty(len(y)); ranks[order] = np.arange(1, len(y) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def prf(pred, y):
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum()); fn = int(((pred == 0) & (y == 1)).sum())
    return {"precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "tp": tp, "fp": fp, "fn": fn}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--l2", type=float, default=0.1); ap.add_argument("--epochs", type=int, default=2000); ap.add_argument("--lr", type=float, default=0.1)
    ap.add_argument("--threshold", type=float, default=0.5)
    a = ap.parse_args()
    rows, keys, X, y = load()
    split = np.array([r["split"] for r in rows]); tr = split == "train"
    if tr.sum() == 0: raise SystemExit("no training rows — run ar_dataset.py first")
    mu = X[tr].mean(0); sd = X[tr].std(0); sd[sd < 1e-9] = 1.0
    Z = (X - mu) / sd
    w, b = fit(Z[tr], y[tr], a.l2, a.epochs, a.lr)
    scores = 1 / (1 + np.exp(-(Z @ w + b)))
    pred = (scores >= a.threshold).astype(int)
    guard = np.array([int(r["guard_severity"] >= 2) for r in rows])

    report = {"model": "logreg(l2=%g, balanced)" % a.l2, "n_features": len(keys), "threshold": a.threshold, "splits": {}}
    for s in ("train", "dev", "test"):
        m = split == s
        if m.sum() == 0: continue
        report["splits"][s] = {"events": int(m.sum()), "positive": int(y[m].sum()),
                               "model": {**prf(pred[m], y[m]), "auc": None if auc(scores[m], y[m]) is None else round(auc(scores[m], y[m]), 3)},
                               "guard_rules": prf(guard[m], y[m])}
    fam_rec = collections.defaultdict(lambda: [0, 0])
    for r, p, yy in zip(rows, pred, y):
        if yy == 1 and r["split"] != "train": fam_rec[r["family"]][0] += int(p == 1); fam_rec[r["family"]][1] += 1
    report["recall_per_family_heldout"] = {k: f"{v[0]}/{v[1]}" for k, v in sorted(fam_rec.items())}
    top = sorted(zip(keys, w), key=lambda kv: -abs(kv[1]))[:12]
    report["top_weights"] = [{"feature": k, "w": round(float(v), 3)} for k, v in top]
    disagreements = [{"id": r["id"], "y": int(yy), "guard": int(g), "model_p": round(float(sc), 3)}
                     for r, yy, g, sc, p in zip(rows, y, guard, scores, pred) if r["split"] != "train" and (g != yy) and (p == yy)]
    report["heldout_fixed_by_model"] = disagreements[:20]

    json.dump({"features": keys, "mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist(), "b": float(b), "threshold": a.threshold, "report": report},
              open(OUT, "w"), indent=1)
    print(json.dumps(report, indent=1)); print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
