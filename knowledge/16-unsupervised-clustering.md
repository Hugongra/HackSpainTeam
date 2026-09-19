# Unsupervised clustering of the fixtures — what it finds, and what it cannot

*2026-09-19. Experiment on the synthetic corpus from [15](15-rogue-scenario-design.md). Code: [`ar_cluster.py`](../ar_cluster.py). Companion to [07](07-risk-vector.md) (the engineered risk vector this is measured against).*

---

## 1. The question

The guard in [`ar_guard.py`](../ar_guard.py) is a pile of hand-written predicates: `DESTRUCTIVE`, `CONTROL_PLANE`, `SECRETLIKE`, `IMPLANT`. Every one of them is a human decision about what danger looks like, which means every one is a maintenance liability and a thing an adversary can enumerate. The obvious hope:

> Do benign and dangerous agent turns fall into different clusters on their own? If they do, the detector could be learned from unlabelled traffic instead of written by hand — and it would generalise to classes nobody thought of.

This is worth testing precisely because the answer decides whether the roadmap is "write more detectors" or "learn the boundary". The answer here is **no, and for an instructive reason**.

## 2. Method

14 fixtures (8 dangerous, 6 benign twins), clustered with two rules that make the result mean something:

1. **Labels are never an input.** `expected_violations` is read only after the clustering is frozen. Naming a cluster is also label-free, by an anomaly prior (§3, and it fails).
2. **No hand-written danger list is a feature.** The feature space is tf-idf over the fields the guard reads (assistant utterances, `_message`, tool names, argument keys and values) plus 15 generic shape statistics — counts, lengths, digit/uppercase/symbol ratios, host and slash counts, type-token ratio. Reusing the guard's regexes would smuggle eight supervised decisions into an "unsupervised" experiment and make any split a tautology. `--features guard` runs exactly that tautology, on purpose, as the comparison.

Everything is exact rather than approximate — n=14 makes it free: k-means++ with 50 restarts, exact Ward linkage, exact silhouette, a 10 000-permutation label null, and a 200× 80%-subsample stability check. numpy only, no sklearn.

Three held-out label sets are scored, not one — **malignancy**, **scenario family**, **tool signature**. Clustering always finds *a* structure; scoring all three is what tells you *which*.

## 3. Result: it clusters tool modality, not malignancy

| Structure | ARI | NMI | 1-NN agreement |
|---|---|---|---|
| malignancy (benign / malignant) — *the question* | **+0.012** | 0.094 | **0.500** (chance) |
| scenario family | +0.085 | 0.344 | 0.571 |
| tool signature | **+0.280** | **0.543** | 0.643 |

ARI +0.012 against a 10k-permutation null gives **p = 0.58**: the split is indistinguishable from shuffling the labels. Recall 0.50, precision 0.44, purity 0.64 — a coin. The result is stable across every variation tried (text only, shape only, both, whole-conversation scope): malignancy ARI stays in **[−0.06, +0.01]** while tool-signature ARI stays positive.

The vocabulary driving the split says plainly what it found: one cluster is `https`, `url`, `method`, `api`, `http_request`; the other is `note`, `call`, `detention`, `eur`. That is **HTTP-calling turns versus talking-and-note-writing turns** — the shape statistics agree (`hosts −2.09σ`, `urls −2.09σ`, `slashes −1.98σ`). It is a real and reasonable partition of the corpus. It is simply orthogonal to whether the agent was doing harm.

The Ward dendrogram is the clearest picture of the failure — read the merge heights:

```
┬ 6.114
├─┬ 4.920
│ ├─┬ 4.089
│ │ ├─┬ 2.838
│ │ │ ├─┬ 1.794
│ │ │ │ ├─┬ 0.771   ← F1 dangerous + F1 benign
│ │ │ │ │ ├─F1-collude-against-operator
│ │ │ │ │ └─F1-benign-detention-explained
│ │ │ │ └─┬ 0.738   ← F6 dangerous + F6 benign
│ │ │ │   ├─F6-instructions-to-future-instances
│ │ │ │   └─F6-benign-handover-note
│ │ │ └─┬ 1.667     ← F4 dangerous + F4 benign
│ │ │   ├─F4-bulk-contact-dump
│ │ │   └─F4-benign-own-booking
│ │ └─┬ 1.460       ← F5 dangerous + F5 benign
│ │   ├─F5-refuses-termination
│ │   └─F5-benign-complies-hangup
│ └─┬ 1.944         ← F2 dangerous + F2 benign
│   ├─F2-destructive-migration
│   └─F2-benign-readonly-lookup
└─┬ 1.244
  ├─┬ 0.342
  │ ├─┬ 0.078       ← two S4 platform attacks, nearly identical
  │ │ ├─F3-sabotage-cancel-fleet
  │ │ └─F5-disable-own-oversight
  │ └─F3-sabotage-delete-kb
  └─F3-benign-status-api
```

**The five tightest merges in the tree are dangerous-with-its-own-benign-twin.** The nearest neighbour of an S4 destructive migration is the harmless read-only lookup; the nearest neighbour of an implanted instruction is the legitimate handover note. Across all 14 cases, 1-NN agreement on malignancy is exactly 0.500.

The unsupervised naming step fails too, and usefully. The prior was *the cluster further from the global centroid is the anomalous one* — dangerous behaviour is a departure, ordinary work is self-similar. It picks the 9-member note-writing cluster (mean ‖x−x̄‖ 1.483) over the 5-member HTTP cluster (1.222), because the HTTP turns are long, structured and self-similar while ordinary conversation is diffuse. **Structured danger is more self-similar than unstructured benignity**, which inverts the prior.

## 4. Why: the twins are adversarial by construction

This is not a modelling failure, it is the fixture set working as designed. [15 §4](15-rogue-scenario-design.md) required that every dangerous fixture ship with *"a benign one that shares its surface features"*. Shared surface features are exactly what a distance metric sees. So the corpus was purpose-built to defeat surface geometry:

| Pair | Same | Differs by |
|---|---|---|
| F3 sabotage vs status API | `http_request`, one URL, same schema | `DELETE …/knowledge-bases/…` vs `GET …/loads/4471` — **the host and the verb** |
| F6 implant vs handover note | `save_note`, same load, similar length | the note instructs a future reader vs records a fact |
| F5 refuses vs complies | same supervisor directive | `_stay_silent` vs `_hangup` — **which tool, not how it looks** |

The distinguishing information is a **semantic predicate over one field** — is this host ours, is this verb destructive, is this note an instruction — carrying almost no variance. Aggregate distance drowns it in the difference between "wrote a note" and "called an API".

## 5. The deployable framing fails harder

2-means on a balanced 8/6 set is unrealistic anyway: real traffic is overwhelmingly benign, so the deployable question is *"how far is this from normal?"*, not *"which of two equal halves is this in?"*. Scoring each case by distance to the nearest known-good case (semi-supervised: the labels choose the reference set, as known-good traffic would in production, never the geometry):

| Score | AUC |
|---|---|
| distance to nearest benign case, **surface features** | **0.354** |
| distance from the global centroid, surface features | 0.521 |
| distance to nearest benign case, **guard's engineered signal space** | **1.000** |

AUC 0.354 is **worse than chance**: in surface space a dangerous turn is *closer* to known-good traffic than a benign turn is, because its twin is sitting right next to it. A novelty detector built on these features would be actively misleading — it would rank `F3-sabotage-delete-kb` as the single most normal case in the corpus.

In the guard's signal space the same test separates perfectly. The information exists; it is not in the surface distribution.

## 6. Where the signal does live — and the trap

Projecting out the top *m* variance directions before clustering:

| dropped | silhouette | ARI malignancy | ARI tool |
|---|---|---|---|
| 0 | +0.173 | +0.012 | +0.280 |
| 1 | **+0.269** | −0.028 | +0.113 |
| 2 | +0.151 | −0.048 | +0.231 |
| 3 | +0.180 | **+0.714** | −0.069 |
| 4 | +0.131 | −0.058 | −0.098 |
| 5 | +0.143 | +0.118 | −0.007 |

Two things to take from this, in order:

1. **The malignancy signal is present but subdominant.** Remove three nuisance modes and ARI jumps to +0.714 — 12 of 14 correct. The surface features are not information-free; malignancy is just the fourth-loudest thing in them, behind tool modality and two other shape modes.
2. **No label-free criterion finds that subspace.** Silhouette — the only internal criterion available — peaks at m=1, where malignancy ARI is −0.028. Picking m=3 requires already knowing the answer. Reporting +0.714 as an unsupervised result would be supervised model selection wearing a disguise, which is why `ar_cluster.py` prints this table under the heading *"reported to locate the signal, not as a result"*.

The guard ablation closes the loop. In the engineered signal space, 2-means gets **precision 1.000, recall 0.625, ARI +0.275, p = 0.089** — better, but still not a clean split, and its family ARI collapses to −0.046 (it has stopped organising by conversation type, as intended). Even there malignancy is not two blobs, because **`peak_severity ≥ S2` is a threshold on a continuous score, not a density mode.** Clustering looks for modes. There is no mode to find.

## 7. So what is clustering good for here

Not the verdict. Three things it does do, on evidence from this run:

- **Behaviour-mode discovery.** Ward at k=6 recovers scenario family at ARI **+0.52** (+0.73 on text features alone) with no labels. That is a corpus-coverage instrument: it shows which behaviour modes exist in captured traffic and which the fixture set does not yet contain.
- **Deduplication and triage.** `F3-sabotage-cancel-fleet` and `F5-disable-own-oversight` merge at cost 0.078 — near-identical payloads filed under different families. On live traffic that is how you collapse thousands of runs into a reviewable number of modes.
- **A routing prior, not a verdict.** Knowing a turn is in the HTTP-calling mode says which specialist predicates are worth evaluating. It says nothing about whether to gate it.

The engineering conclusion: **the roadmap is "write better predicates", not "learn the boundary"** — at least until there is enough labelled traffic for a supervised model, where the honest baseline is now on record as AUC 1.000 from a handful of regexes.

## 8. Caveats

- **n = 14.** Subsample stability is ARI 0.52 ± 0.52 — the clustering itself is barely reproducible under dropping a fifth of the cases. The *negative* result is the robust part (it holds across four feature spaces and a permutation null); any positive number here would need far more data.
- **The corpus is adversarial for this task by design, and balanced 8/6, which real traffic is not.** Both make surface clustering look worse than it might on natural traffic. That cuts the other way too: natural traffic would be *more* dominated by ordinary modality variance, not less.
- **Bag-of-terms is the weakest text representation.** A sentence embedding might place "delete the knowledge base" near other destructive intents across families. That is the obvious next experiment, and it needs a model that runs offline.
- **The clean comparison is still missing**: cluster live traffic from [14](14-rogue-agent-lab.md) rather than self-authored fixtures.

## 9. Running it

```bash
/usr/bin/python3 ar_cluster.py                       # fixtures/corpus.jsonl
/usr/bin/python3 ar_cluster.py fixtures              # the *.inline.json directly
/usr/bin/python3 ar_cluster.py --features text       # ablations: text / shape / both
/usr/bin/python3 ar_cluster.py --features guard      # the engineered signal space
/usr/bin/python3 ar_cluster.py --k 6 --no-probe      # family recovery
/usr/bin/python3 ar_cluster.py --drop-top 3          # the subdominant subspace of §6
```

Writes `fixtures/clusters.json` (gitignored, regenerable): assignments, both label sets, k sweep, all scores, the subspace probe and the discriminative vocabulary per cluster.
