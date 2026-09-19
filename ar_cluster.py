#!/usr/bin/env python3
"""
ar_cluster — unsupervised clustering of the fixture corpus.

Question: does the *shape* of what an agent says and calls separate the benign
cases from the dangerous ones on its own, with nobody telling it what danger
looks like?

    /usr/bin/python3 ar_cluster.py                      # fixtures/corpus.jsonl
    /usr/bin/python3 ar_cluster.py fixtures             # the *.inline.json directly
    /usr/bin/python3 ar_cluster.py --features guard     # ablation (see below)

Two rules make the answer mean something:

  1. **The labels are never an input.** `expected_violations` is read only after
     the clustering is fixed, to score it. Naming a cluster is also done without
     them, by an anomaly prior (§naming).
  2. **No hand-written danger list is a feature.** The feature space is tf-idf
     over the fields the guard reads plus generic shape statistics (counts,
     lengths, character ratios). `ar_guard`'s DESTRUCTIVE / CONTROL_PLANE /
     SECRETLIKE regexes are deliberately excluded — reusing them would smuggle
     eight supervised decisions into an "unsupervised" experiment and make the
     split a tautology. `--features guard` runs that tautology on purpose, as a
     comparison.

Three held-out label sets are scored, not one: malignancy (the question),
scenario family, and tool signature. Clustering will happily find *a* structure;
scoring all three is what tells you **which** structure it found.

Implemented on numpy alone — n=14, so everything is exact rather than
approximate: full k-means++ restarts, exact Ward linkage, exact silhouette, a
10k-permutation null and a subsample stability check.
"""
import argparse, glob, json, math, os, re
import numpy as np

TOKEN = re.compile(r"[a-z][a-z0-9_]+")
URL = re.compile(r"https?://([a-z0-9.\-]+)", re.I)


# ── loading ──────────────────────────────────────────────────────────────────
def load(path):
    """Accept corpus.jsonl, a single *.inline.json, or a directory of fixtures."""
    if os.path.isdir(path):
        files = sorted(glob.glob(os.path.join(path, "*.inline.json")))
        if files:
            from ar_fixtures import to_corpus
            return [to_corpus(json.load(open(f))) for f in files]
        path = os.path.join(path, "corpus.jsonl")
    if path.endswith(".jsonl"):
        return [json.loads(l) for l in open(path) if l.strip()]
    from ar_fixtures import to_corpus
    return [to_corpus(json.load(open(path)))]


def agent_side(rec):
    """What the agent itself produced: utterances (incl. `_message`) and tool calls."""
    utter, calls = [], []
    for t in rec.get("turns", []):
        if t.get("role") != "assistant":
            continue
        utter.append(t.get("content") or "")
        for tc in (t.get("tool_calls") or []):
            args = dict(tc.get("arguments") or {})
            if "_message" in args:                       # the agent speaking, not an argument
                utter.append(str(args.pop("_message")))
            calls.append({"name": tc.get("name") or "", "args": args})
    return "\n".join(u for u in utter if u), calls


# ── features: bag of terms ────────────────────────────────────────────────────
def document(rec, scope="agent"):
    utter, calls = agent_side(rec)
    parts = [utter]
    for c in calls:
        parts.append(c["name"])
        for k, v in c["args"].items():
            parts.append(f"{k} {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}")
    if scope == "all":
        parts += [t.get("content") or "" for t in rec.get("turns", []) if t.get("role") != "assistant"]
        parts += list(rec.get("tools_offered") or [])
    return "\n".join(p for p in parts if p)


def terms(text, ngram=2):
    ws = TOKEN.findall(text.lower())
    out = list(ws)
    for n in range(2, ngram + 1):
        out += [" ".join(ws[i:i + n]) for i in range(len(ws) - n + 1)]
    return out


def tfidf(docs, ngram=2, min_df=2):
    """Sublinear tf × smoothed idf, L2-normalised rows.

    min_df=2 is a prior, not a tuned knob: a term seen in one case only is an
    idiosyncrasy of that fixture, and with n=14 those would dominate the geometry.
    """
    bags = [terms(d, ngram) for d in docs]
    df = {}
    for b in bags:
        for t in set(b):
            df[t] = df.get(t, 0) + 1
    vocab = sorted(t for t, c in df.items() if c >= min_df)
    if not vocab:
        return np.zeros((len(docs), 0)), []
    idx = {t: i for i, t in enumerate(vocab)}
    X = np.zeros((len(docs), len(vocab)))
    for i, b in enumerate(bags):
        for t in b:
            j = idx.get(t)
            if j is not None:
                X[i, j] += 1
    X = np.where(X > 0, 1 + np.log(np.maximum(X, 1)), 0.0)
    X *= np.log((1 + len(docs)) / (1 + np.array([df[t] for t in vocab]))) + 1
    nrm = np.linalg.norm(X, axis=1, keepdims=True)
    nrm[nrm == 0] = 1
    return X / nrm, vocab


# ── features: shape statistics ────────────────────────────────────────────────
def structural(rec):
    """Generic descriptors of the payload's form. Nothing here knows what danger
    is: `upper_ratio` rises for DROP TABLE and DELETE, but equally for GET."""
    utter, calls = agent_side(rec)
    blob = json.dumps([c["args"] for c in calls], ensure_ascii=False)
    values = [str(v) for c in calls for v in c["args"].values()]
    toks = TOKEN.findall(utter.lower())
    n = max(len(blob), 1)
    letters = max(sum(ch.isalpha() for ch in blob), 1)
    return {
        "tool_calls": len(calls),
        "assistant_turns": sum(1 for t in rec.get("turns", []) if t.get("role") == "assistant"),
        "tools_offered": len(rec.get("tools_offered") or []),
        "arg_chars": len(blob),
        "arg_keys": sum(len(c["args"]) for c in calls),
        "max_value_chars": max((len(v) for v in values), default=0),
        "urls": len(URL.findall(blob)),
        "hosts": len({h.lower() for h in URL.findall(blob)}),
        "digit_ratio": sum(ch.isdigit() for ch in blob) / n,
        "upper_ratio": sum(ch.isupper() for ch in blob) / letters,
        "symbol_ratio": sum(not ch.isalnum() and not ch.isspace() for ch in blob) / n,
        "slashes": blob.count("/"),
        "utter_chars": len(utter),
        "utter_terms": len(toks),
        "type_token_ratio": len(set(toks)) / max(len(toks), 1),
    }


SHAPE_KEYS = sorted(structural({"turns": []}))


def guard_features(recs):
    """Ablation only: the guard's own verdict, one-hot. Hand-tuned on this very
    corpus, so a clean split here would prove nothing except that the guard works."""
    from ar_guard import run_case
    cases = [run_case(r) for r in recs]
    sigs = sorted({s["name"] for c in cases for e in c["events"] for s in e["signals"]})
    floors = sorted({k for c in cases for e in c["events"] for k in e["floors"]})
    names = ["events", "peak", "rogue_index"] + [f"S{i}" for i in (1, 2, 3, 4)] \
        + [f"sig:{s}" for s in sigs] + [f"floor:{f}" for f in floors]
    rows = []
    for c in cases:
        have_s = {s["name"] for e in c["events"] for s in e["signals"]}
        have_f = {k for e in c["events"] for k in e["floors"]}
        rows.append([len(c["events"]), c["final"]["peak_severity"], c["final"]["rogue_index"]]
                    + [c["final"]["counts"].get(i, 0) for i in (1, 2, 3, 4)]
                    + [float(s in have_s) for s in sigs] + [float(f in have_f) for f in floors])
    return np.array(rows, float), names


# ── linear algebra ────────────────────────────────────────────────────────────
def zscore(X):
    sd = X.std(0)
    keep = sd > 1e-12
    return (X[:, keep] - X[:, keep].mean(0)) / sd[keep], keep


def pca(X, k):
    Xc = X - X.mean(0)
    U, s, Vt = np.linalg.svd(Xc, full_matrices=False)
    k = min(k, int((s > 1e-10).sum()))
    ev = (s ** 2) / max((s ** 2).sum(), 1e-12)
    return (U[:, :k] * s[:k]), float(ev[:k].sum())


def drop_top(X, m):
    """Project out the m highest-variance directions."""
    Xc = X - X.mean(0)
    if m <= 0:
        return Xc
    U, s, Vt = np.linalg.svd(Xc, full_matrices=False)
    return Xc - (U[:, :m] * s[:m]) @ Vt[:m]


def unit(X, w):
    """Scale a block so its mean squared row norm is 1, then weight it, so text
    and shape contribute comparably rather than by accident of dimensionality."""
    if X.size == 0:
        return X
    rms = math.sqrt((X ** 2).sum() / len(X)) or 1.0
    return X * (w / rms)


# ── clustering ────────────────────────────────────────────────────────────────
def kmeans(X, k, seed=0, n_init=50, iters=300):
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(n_init):
        C = [X[rng.integers(len(X))]]
        for _ in range(k - 1):                            # k-means++ seeding
            d2 = ((X[:, None, :] - np.array(C)[None, :, :]) ** 2).sum(-1).min(1)
            C.append(X[rng.choice(len(X), p=d2 / d2.sum()) if d2.sum() > 0 else rng.integers(len(X))])
        C = np.array(C, float)
        lab = np.zeros(len(X), int)
        for _ in range(iters):
            lab = ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1).argmin(1)
            new = np.array([X[lab == j].mean(0) if np.any(lab == j) else X[rng.integers(len(X))]
                            for j in range(k)])
            if np.allclose(new, C):
                break
            C = new
        inertia = float(((X - C[lab]) ** 2).sum())
        if best is None or inertia < best[0] - 1e-12:
            best = (inertia, lab.copy(), C.copy())
    return best[1], best[2], best[0]


def ward(X):
    """Exact Ward: merge the pair with the smallest increase in within-cluster sum
    of squares, which for centroids is n_a·n_b/(n_a+n_b)·d². O(n³), and n=14, so
    there is no reason to approximate."""
    groups = [[i] for i in range(len(X))]
    history = []
    while len(groups) > 1:
        best = None
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                na, nb = len(groups[a]), len(groups[b])
                d = X[groups[a]].mean(0) - X[groups[b]].mean(0)
                cost = na * nb / (na + nb) * float(d @ d)
                if best is None or cost < best[0] - 1e-15:
                    best = (cost, a, b)
        cost, a, b = best
        history.append((list(groups[a]), list(groups[b]), cost))
        groups[a] = groups[a] + groups[b]
        del groups[b]
    return history


def cut(history, n, k):
    groups = [[i] for i in range(n)]
    for a, b, _ in history[:max(0, n - k)]:
        ga = next(g for g in groups if set(g) & set(a))
        gb = next(g for g in groups if set(g) & set(b))
        groups.remove(gb)
        ga.extend(gb)
    lab = np.zeros(n, int)
    for j, g in enumerate(sorted(groups, key=min)):
        for i in g:
            lab[i] = j
    return lab


def dendrogram(history, names):
    n = len(names)
    node = {i: ("leaf", names[i]) for i in range(n)}
    key = {frozenset([i]): i for i in range(n)}
    nxt = n
    for a, b, cost in history:
        node[nxt] = ("node", key[frozenset(a)], key[frozenset(b)], cost)
        key[frozenset(a + b)] = nxt
        nxt += 1

    def walk(nid, prefix, conn, out):
        e = node[nid]
        if e[0] == "leaf":
            out.append(f"{prefix}{conn}{e[1]}")
            return out
        _, ka, kb, cost = e
        out.append(f"{prefix}{conn}┬ {cost:.3f}")
        inner = prefix + ("" if conn == "" else ("│ " if conn == "├─" else "  "))
        walk(ka, inner, "├─", out)
        walk(kb, inner, "└─", out)
        return out

    return walk(nxt - 1, "", "", [])


def distances(X):
    D = np.sqrt(np.maximum(((X[:, None, :] - X[None, :, :]) ** 2).sum(-1), 0))
    return D


def silhouette(X, lab):
    D = distances(X)
    out = []
    for i in range(len(X)):
        own = lab == lab[i]
        own[i] = False
        others = [c for c in set(lab.tolist()) if c != lab[i]]
        if not own.any() or not others:
            out.append(0.0)
            continue
        a = D[i, own].mean()
        b = min(D[i, lab == c].mean() for c in others)
        out.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return float(np.mean(out))


def nearest(X):
    D = distances(X)
    np.fill_diagonal(D, np.inf)
    return D.argmin(1)


# ── agreement measures (labels enter only here) ───────────────────────────────
def contingency(a, b):
    ca, cb = sorted(set(a)), sorted(set(b))
    M = np.zeros((len(ca), len(cb)), int)
    for x, y in zip(a, b):
        M[ca.index(x), cb.index(y)] += 1
    return M, ca, cb


def _c2(x):
    return x * (x - 1) / 2


def ari(a, b):
    M, _, _ = contingency(list(a), list(b))
    sij, si, sj = _c2(M).sum(), _c2(M.sum(1)).sum(), _c2(M.sum(0)).sum()
    exp = si * sj / _c2(M.sum())
    mx = (si + sj) / 2
    return 1.0 if mx == exp else float((sij - exp) / (mx - exp))


def nmi(a, b):
    M, _, _ = contingency(list(a), list(b))
    P = M / M.sum()
    pi, pj = P.sum(1), P.sum(0)
    mi = sum(P[i, j] * math.log(P[i, j] / (pi[i] * pj[j]))
             for i in range(P.shape[0]) for j in range(P.shape[1]) if P[i, j] > 0)
    h = lambda p: -sum(x * math.log(x) for x in p if x > 0)
    d = (h(pi) + h(pj)) / 2
    return 1.0 if d <= 0 else float(mi / d)


def purity(lab, truth):
    M, _, _ = contingency(list(lab), list(truth))
    return float(M.max(1).sum() / M.sum())


def permutation_p(lab, truth, rounds=10000, seed=0):
    obs = ari(lab, truth)
    rng = np.random.default_rng(seed)
    t = np.array(truth)
    ge = sum(ari(lab, rng.permutation(t)) >= obs - 1e-12 for _ in range(rounds))
    return obs, (1 + ge) / (1 + rounds)


def stability(X, k, frac=0.8, rounds=200, seed=0):
    """Would the same split survive dropping a fifth of the cases? With n=14 a
    clustering can be an artefact of two or three points; this says how much."""
    rng = np.random.default_rng(seed)
    full = kmeans(X, k, seed=seed)[0]
    m = max(k + 1, int(round(frac * len(X))))
    out = []
    for _ in range(rounds):
        idx = rng.choice(len(X), m, replace=False)
        lab = kmeans(X[idx], k, seed=int(rng.integers(10 ** 6)), n_init=10)[0]
        out.append(ari(lab, full[idx]))
    return float(np.mean(out)), float(np.std(out))


def discriminative(T, vocab, lab, c, top=8):
    if not vocab or not (lab != c).any():
        return []
    d = T[lab == c].mean(0) - T[lab != c].mean(0)
    return [(vocab[j], round(float(d[j]), 4)) for j in np.argsort(-d)[:top] if d[j] > 0]


def auc(score, y):
    """Probability that a malignant case outranks a benign one; 0.5 is chance."""
    pos, neg = np.asarray(score)[np.asarray(y) == 1], np.asarray(score)[np.asarray(y) == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    return float(np.mean([(p > q) + 0.5 * (p == q) for p in pos for q in neg]))


def novelty(X, y, knn=1):
    """Distance to the nearest known-good case. This is the realistic framing —
    real traffic is overwhelmingly benign, so the deployable question is "how far
    is this from normal?", not "which of two equal halves is this in?". It is
    semi-supervised: the labels choose the reference set (in production, known-good
    traffic does), never the geometry."""
    D = distances(X)
    ref = [i for i, t in enumerate(y) if not t]
    return np.array([np.mean(sorted(D[i, j] for j in ref if j != i)[:knn]) for i in range(len(X))])


# ── report ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="unsupervised clustering of the rogue-agent fixtures")
    ap.add_argument("path", nargs="?", default=os.path.join("fixtures", "corpus.jsonl"))
    ap.add_argument("--features", choices=["both", "text", "shape", "guard"], default="both")
    ap.add_argument("--scope", choices=["agent", "all"], default="agent",
                    help="agent = the agent's own output only; all = the whole conversation")
    ap.add_argument("--k", type=int, default=2, help="clusters in the reported solution")
    ap.add_argument("--kmax", type=int, default=6, help="upper bound of the silhouette sweep")
    ap.add_argument("--ngram", type=int, default=2)
    ap.add_argument("--min-df", type=int, default=2)
    ap.add_argument("--comps", type=int, default=8, help="PCA components kept from the text block")
    ap.add_argument("--text-weight", type=float, default=1.0)
    ap.add_argument("--shape-weight", type=float, default=1.0)
    ap.add_argument("--drop-top", type=int, default=0,
                    help="project out the m highest-variance directions before clustering")
    ap.add_argument("--no-probe", action="store_true", help="skip the subspace diagnostic")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    recs = load(a.path)
    names = [r.get("case_id") or r.get("persona") for r in recs]
    n = len(recs)

    # ---- feature space (no label, and no danger list, enters here) ----
    T, vocab, shape_names, S, var = np.zeros((n, 0)), [], [], None, None
    if a.features == "guard":
        G, gn = guard_features(recs)
        S, keep = zscore(G)
        shape_names = [s for s, k in zip(gn, keep) if k]
        X = unit(S, 1.0)
        desc = f"{S.shape[1]} guard signals (ABLATION — hand-tuned on this corpus)"
    else:
        blocks, bits = [], []
        if a.features in ("both", "text"):
            T, vocab = tfidf([document(r, a.scope) for r in recs], a.ngram, a.min_df)
            P, var = pca(T, a.comps)
            blocks.append(unit(P, a.text_weight))
            bits.append(f"{len(vocab)} tf-idf terms → {P.shape[1]} PCA comps ({var:.1%} var)")
        if a.features in ("both", "shape"):
            rows = [structural(r) for r in recs]
            S, keep = zscore(np.array([[r[k] for k in SHAPE_KEYS] for r in rows], float))
            shape_names = [s for s, k in zip(SHAPE_KEYS, keep) if k]
            blocks.append(unit(S, a.shape_weight))
            bits.append(f"{len(shape_names)} shape stats")
        X = np.hstack(blocks)
        desc = " + ".join(bits)
    if a.drop_top:
        X = drop_top(X, a.drop_top)
        desc += f" · top {a.drop_top} variance direction(s) projected out"

    print(f"\nar_cluster · {n} cases · {desc}")
    print(f"feature matrix {X.shape[0]}×{X.shape[1]} · labels held out until §scoring\n")

    # ---- how many clusters does the geometry want? ----
    sweep = {}
    for k in range(2, min(a.kmax, n - 1) + 1):
        lab, _, inertia = kmeans(X, k, seed=a.seed)
        sweep[k] = {"silhouette": round(silhouette(X, lab), 3), "inertia": round(inertia, 3)}
    kbest = max(sweep, key=lambda k: sweep[k]["silhouette"])
    print("── k sweep (k-means, 50 restarts; silhouette is the only criterion available"
          " without labels) ──")
    for k, v in sweep.items():
        print(f"  k={k}  silhouette {v['silhouette']:+.3f}  inertia {v['inertia']:8.3f}"
              f"{'   ← preferred' if k == kbest else ''}")

    lab, _, _ = kmeans(X, a.k, seed=a.seed)
    hier = ward(X)
    hlab = cut(hier, n, a.k)

    print("\n── hierarchical (Ward, exact; heights are merge costs) ──")
    for line in dendrogram(hier, names):
        print("  " + line)

    # ---- naming the clusters without labels ----
    # Prior: the cluster sitting further from the global centroid is the anomalous
    # one — dangerous behaviour is a departure from the ordinary, ordinary work is
    # self-similar. That is one bit of inductive bias, not one bit of the answer.
    dist = np.linalg.norm(X - X.mean(0), axis=1)
    spread = {c: float(dist[lab == c].mean()) for c in sorted(set(lab.tolist()))}
    anom = max(spread, key=spread.get)
    print("\n── naming, unsupervised (mean distance from the global centroid) ──")
    for c, d in spread.items():
        print(f"  cluster {c}  n={int((lab == c).sum()):2}  mean ‖x−x̄‖ {d:.3f}"
              f"{'   → called ANOMALOUS' if c == anom else '   → called ordinary'}")

    # ---- three held-out label sets: which structure did we actually find? ----
    truth = [1 if r.get("expected_violations") else 0 for r in recs]
    family = [(r.get("trigger") or "?").split("—")[0].strip() for r in recs]
    toolsig = ["|".join(sorted({c["name"] for c in agent_side(r)[1]})) or "none" for r in recs]
    pred = [1 if c == anom else 0 for c in lab]
    tp = sum(1 for p, t in zip(pred, truth) if p and t)
    fp = sum(1 for p, t in zip(pred, truth) if p and not t)
    fn = sum(1 for p, t in zip(pred, truth) if not p and t)
    tn = sum(1 for p, t in zip(pred, truth) if not p and not t)

    print("\n── assignment ──")
    print(f"  {'case':38}{'k-means':>8}{'ward':>6}{'‖x−x̄‖':>9}  {'truth':10}{'family':26} nearest neighbour")
    nn = nearest(X)
    for i in sorted(range(n), key=lambda i: (lab[i], names[i])):
        print(f"  {names[i]:38}{lab[i]:>8}{hlab[i]:>6}{dist[i]:>9.3f}  "
              f"{'malignant' if truth[i] else 'benign':10}{family[i]:26} {names[nn[i]]}"
              f"{'' if truth[i] == truth[nn[i]] else '  ← opposite class'}")

    print("\n── which structure did the clustering find? ──")
    for nm, ref in (("malignancy (benign / malignant)", truth), ("scenario family", family),
                    ("tool signature", toolsig)):
        knn = float(np.mean([ref[i] == ref[j] for i, j in enumerate(nn)]))
        print(f"  {nm:32} ARI {ari(lab, ref):+.3f}   NMI {nmi(lab, ref):.3f}   "
              f"1-NN agreement {knn:.3f}")
    kf = min(len(set(family)), n - 1)
    print(f"  at k={kf} (one cluster per family): k-means vs family ARI {ari(kmeans(X, kf, seed=a.seed)[0], family):+.3f}"
          f" · Ward vs family ARI {ari(cut(hier, n, kf), family):+.3f}")

    obs_ari, p = permutation_p(lab, truth, seed=a.seed)
    st_mean, st_sd = stability(X, a.k, seed=a.seed)
    scoring = {
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "purity": round(purity(lab, truth), 3), "ari": round(obs_ari, 3), "ari_p_value": round(p, 5),
        "nmi": round(nmi(lab, truth), 3),
        "ari_vs_family": round(ari(lab, family), 3), "ari_vs_toolsig": round(ari(lab, toolsig), 3),
        "ari_ward_vs_truth": round(ari(hlab, truth), 3),
        "ari_kmeans_vs_ward": round(ari(lab, hlab), 3),
        "silhouette": round(silhouette(X, lab), 3),
        "recall": round(tp / max(tp + fn, 1), 3), "precision": round(tp / max(tp + fp, 1), 3),
        "knn_agreement": {"malignancy": round(float(np.mean([truth[i] == truth[j] for i, j in enumerate(nn)])), 3),
                          "family": round(float(np.mean([family[i] == family[j] for i, j in enumerate(nn)])), 3),
                          "toolsig": round(float(np.mean([toolsig[i] == toolsig[j] for i, j in enumerate(nn)])), 3)},
        "stability_ari": [round(st_mean, 3), round(st_sd, 3)],
    }
    print("\n── scoring the malignancy question ──")
    print(f"  malignant inside the anomalous cluster {tp}/{tp + fn} · benign kept out {tn}/{tn + fp}")
    print(f"  recall {scoring['recall']:.3f} · precision {scoring['precision']:.3f} · purity {scoring['purity']:.3f}")
    print(f"  ARI {obs_ari:+.3f} against a 10k label-permutation null: p = {p:.4f}")
    print(f"  Ward vs truth ARI {scoring['ari_ward_vs_truth']:+.3f} · k-means vs Ward ARI {scoring['ari_kmeans_vs_ward']:+.3f}")
    print(f"  stability over 200× 80% subsamples: ARI {st_mean:.3f} ± {st_sd:.3f}")

    # ---- what the split keyed on ----
    print("\n── what separates the clusters ──")
    for c in sorted(set(lab.tolist())):
        tag = "ANOMALOUS" if c == anom else "ordinary "
        tt = discriminative(T, vocab, lab, c)
        if tt:
            print(f"  {tag} c{c} terms:  " + ", ".join(f"{t} {v:+.3f}" for t, v in tt))
    if S is not None and shape_names and (lab != anom).any():
        d = S[lab == anom].mean(0) - S[lab != anom].mean(0)
        print(f"  ANOMALOUS c{anom} shape: "
              + ", ".join(f"{shape_names[j]} {d[j]:+.2f}σ" for j in np.argsort(-np.abs(d))[:6]))

    # ---- the deployable framing: distance from known-good ----
    nv = novelty(X, truth)
    scoring["novelty_auc"] = round(auc(nv, truth), 3)
    scoring["outlierness_auc"] = round(auc(dist, truth), 3)
    print("\n── novelty against a known-good reference (semi-supervised: labels pick the"
          " reference set, not the geometry) ──")
    print(f"  distance to nearest benign case, AUC {scoring['novelty_auc']:.3f}"
          f"   ·  distance from the global centroid, AUC {scoring['outlierness_auc']:.3f}"
          "   (0.5 = chance)")
    if a.features != "guard":
        Gp, _ = guard_features(recs)
        Xg = unit(zscore(Gp)[0], 1.0)
        scoring["novelty_auc_guard_space"] = round(auc(novelty(Xg, truth), truth), 3)
        print(f"  the same test in the guard's engineered signal space, AUC "
              f"{scoring['novelty_auc_guard_space']:.3f} — that is where the separating"
              " information lives")

    # ---- diagnostic: is the signal present but not dominant? ----
    probe = {}
    if not a.no_probe and a.drop_top == 0 and X.shape[1] > 6:
        print("\n── diagnostic: where does the malignancy signal sit in the variance spectrum? ──")
        print(f"  {'dropped':>7}{'silhouette':>12}{'ARI malignancy':>16}{'ARI tool':>10}")
        for m in range(0, 6):
            R = drop_top(X, m)
            l2, _, _ = kmeans(R, a.k, seed=a.seed)
            probe[m] = {"silhouette": round(silhouette(R, l2), 3),
                        "ari_malignancy": round(ari(l2, truth), 3),
                        "ari_toolsig": round(ari(l2, toolsig), 3)}
            print(f"  {m:>7}{probe[m]['silhouette']:>+12.3f}{probe[m]['ari_malignancy']:>+16.3f}"
                  f"{probe[m]['ari_toolsig']:>+10.3f}")
        m_sil = max(probe, key=lambda m: probe[m]["silhouette"])
        m_ari = max(probe, key=lambda m: probe[m]["ari_malignancy"])
        print(f"  silhouette — the only label-free criterion — picks m={m_sil}; malignancy ARI peaks at m={m_ari}.")
        print("  Reported to locate the signal, not as a result: picking m by ARI is supervised model selection.")

    out = a.out or os.path.join(a.path if os.path.isdir(a.path) else (os.path.dirname(a.path) or "."),
                                "clusters.json")
    json.dump({"config": vars(a), "features": desc, "cases": names,
               "kmeans": lab.tolist(), "ward": hlab.tolist(), "anomalous_cluster": int(anom),
               "anomaly_distance": [round(float(x), 4) for x in dist],
               "nearest_neighbour": [names[j] for j in nn],
               "truth_malignant": truth, "family": family, "tool_signature": toolsig,
               "k_sweep": sweep, "scoring": scoring, "subspace_probe": probe,
               "vocabulary_size": len(vocab),
               "discriminative_terms": {str(c): discriminative(T, vocab, lab, c, 12)
                                        for c in sorted(set(lab.tolist()))} if vocab else {}},
              open(out, "w"), indent=1, ensure_ascii=False)
    print(f"\n→ {out}\n")


if __name__ == "__main__":
    main()
