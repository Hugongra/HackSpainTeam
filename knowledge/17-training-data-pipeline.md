# Training-data pipeline — from 23 labelled cases to a dataset the predictive model can learn from

*2026-09-19. Companion to [15](15-rogue-scenario-design.md) (how fixtures are authored), [16](16-unsupervised-clustering.md) (why the model must learn in the guard's signal space, not on raw text) and [07](07-risk-vector.md) (the signal space itself). UI: [`ar_pipeline_ui.py`](../ar_pipeline_ui.py).*

---

## 1. The unit is the event, not the conversation

The guard decides per **event** — a proposed tool call, an utterance, a required action that did not happen. So the training record is one event, carrying three blocks:

| Block | Content | Where it comes from |
|---|---|---|
| `features` | the guard's signal space: impact, R, B, every named signal's p·w, every floor, event kind, tool family, generic shape stats (64 dims) | `ar_guard.run_case` |
| `y_severity` / `y` | severity of the matching `expected_violations` entry (0 if none); `y` = "S2 or higher" | the case's label, attached to the *last* event whose kind matches `where` |
| `split` | train / dev / test **by parent template**, so every mutation and flip of one fixture lands on the same side; live runs are always test | `md5(parent)` |

`guard_severity` (the rule verdict) is stored next to the label but **not** fed as a feature — it is the baseline the model is compared against.

## 2. Four sources, one schema

```
ar_fixtures.py  ─┐                                    ┌─ data/dataset.jsonl
ar_augment.py   ─┼─ ar_lint.py ─ ar_dataset.py ─ ar_train.py ─┤
ar_synth.py     ─┤                                    └─ data/model.json
hr_rogue_lab.py ─┘  (live, real org data, explore/ only)
```

| Source | Script | Cost | What it adds | Label tier |
|---|---|---|---|---|
| hand-written fixtures | `ar_fixtures.py` | 0 | 14 gold cases, 6 benign twins | gold |
| **surface mutations** | `ar_augment.py` | 0 | ids, fictional hosts, phones, rates, greetings, filler turns, tool order, casing — label inherited | gold (inherited) |
| **predicate flips** | `ar_augment.py` | 0 | the one field that decides the verdict is flipped and the label with it: GET→DELETE, `_hangup`→`_stay_silent`, factual note→implanted instruction (9 flips) | gold (authored) |
| Claude-authored | `ar_synth.py` | tokens | new situations per family + twin, structured output, linted before saving | silver |
| live lab | `hr_rogue_lab.py` | ~3.4 credits / conversation | real platform runs, commercial classes only | silver (persona) + platform audits when enabled |

Every generated record passes [`ar_lint.py`](../ar_lint.py): hosts must be `*.invalid`, tokens must contain `FAKE`, phones stay in the fictional range, destructive statements must be `<ELIDED>`. A record that fails is dropped, never written.

## 3. Why the flips matter

[16](16-unsupervised-clustering.md) showed that on surface features a dangerous turn is *closer* to known-good traffic than a benign turn is, because its twin shares the surface. A model trained only on positives-plus-easy-negatives learns "HTTP call ⇒ bad". The flips scale the twins with the positives: for every dangerous template there is a same-surface benign case, and for every benign template a same-surface dangerous one. With the default `--per 8` the 14 fixtures become 193 records, 109 with violations and 84 controls.

First run of the guard over that set: recall 1.0, precision 0.965 — **4 false positives** that the hand-written fixtures never exposed, all on flips. That is the dataset doing its job before any model is trained.

## 4. The model

`ar_train.py` fits a class-balanced L2 logistic regression on the 64 features (numpy only, no sklearn) and reports, per split: precision / recall / AUC of the model, the same for the guard's rules on identical rows, recall per family on held-out data, the heaviest weights, and the held-out events where the model is right and the rules are wrong. It is deliberately small and explainable — the same argument as `angryrobot/learn.py`: at this scale the useful question is *which signals carry weight and where does the learned boundary beat the hand-written one*, not whether a large model can memorise the fixtures.

## 5. Honest caveats

- **Thin split until synth runs.** With 14 parents the hash split puts only two templates in dev and two in test. `ar_synth.py` is what widens it; until then treat held-out numbers as a smoke test.
- **Feature–label coupling.** Features are the guard's signals and labels are human; the model can only rearrange the signals it is given. Signals for classes the guard does not see (F5's *absent* action is the known one) need a new detector first, then data.
- **Live data stays in `explore/`.** Real org transcripts are never committed; the dataset builder reads them if present and holds them out as test.

## 6. Run it

```bash
/usr/bin/python3 ar_pipeline_ui.py          # http://localhost:8793 — buttons for every step and two chains
# or by hand:
/usr/bin/python3 ar_augment.py --per 8 && /usr/bin/python3 ar_lint.py && /usr/bin/python3 ar_dataset.py && /usr/bin/python3 ar_train.py
export ANTHROPIC_API_KEY=…; pip install anthropic; /usr/bin/python3 ar_synth.py --per-family 3
```

`data/` is gitignored (regenerate from the UI); `fixtures/` stays committed.
