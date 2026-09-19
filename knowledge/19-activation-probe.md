# The activation probe — reading latent intent, not surface text

*2026-09-19. A third detection ring for the guard. Code: [`ar_probe.py`](../ar_probe.py); UI section in [`ar_pipeline_ui.py`](../ar_pipeline_ui.py). Companion to [07](07-risk-vector.md) (regex signal space), [16](16-unsupervised-clustering.md) (why surface geometry fails), [18](18-jev-semantic-judge.md) (the semantic judge). Reading list in [`../link`](../link).*

---

## 1. Where this sits

Three rings, each reading one layer deeper than the last:

| Ring | Reads | Mechanism | Cost |
|---|---|---|---|
| `ar_guard` | what the agent **said / called** | regex + typed rules over the completion | free, deterministic |
| `ar_jev` | the **meaning** of that output | typed questions to a System-One model (`noul` probabilities) | ~600 ms / event |
| **`ar_probe`** | the model's **internal state** as it decides | a linear probe on one layer's residual stream | one forward pass + **<1 ms** |

Rings 1–2 are post-hoc: they judge the tokens after they exist. The probe reads the representation *that produced* those tokens, so in principle it can flag intent that the surface text hides — the covert-channel and collusion families ([15 §3](15-rogue-scenario-design.md)) that [16](16-unsupervised-clustering.md) showed are invisible to surface clustering.

## 2. The hypothesis, and why it is credible

From the mechanistic-interpretability literature: high-level concepts are often **linearly represented** in a transformer's residual stream. Zou et al. 2023 (*Representation Engineering*) read and *steer* concepts like honesty and harmfulness with a single direction; Marks & Tegmark 2023 recover truth/falsehood with a linear probe; Anthropic's dictionary-learning work finds linear features for deception-adjacent concepts. If "I am being steered into something harmful" is even approximately a direction, a probe over `hidden_size` floats recovers it — no fine-tuning, no second model.

`ar_probe` implements the two standard readouts of that hypothesis:

- **`probe`** — a linear classifier (scikit-learn `LogisticRegression`/`LinearSVC` if installed, else the numpy class-balanced logistic regression from [`ar_train.py`](../ar_train.py)) on the standardised activation.
- **`repeng`** — representation engineering: one direction, `mean(malicious) − mean(safe)`, score = the calibrated projection onto it. No training loop, interpretable, and the same direction can *steer* generation, not just classify.

## 3. Pipeline

```
prompt ─▶ chat template ─▶ forward pass (output_hidden_states=True)
                                   │
                     hidden_states[layer][last_token]   ← (hidden_size,) vector
                                   │
              standardise ─▶ linear probe ─▶ sigmoid ─▶ malicious_score ∈ [0,1]
```

Design points that matter:

- **Layer.** A mid-to-late layer carries the most abstract features; the default is `-8` (negative = counted from the end) so it works whether the model has 16 layers or 32. Sweeping the layer is the first tuning knob (`--layer`).
- **Token position.** The **last** real token — the position from which the model generates its answer, so its residual stream is conditioned on the whole prompt. Batch of one means no padding to mask.
- **Capture path.** `output_hidden_states=True` is used because it is architecture-agnostic. The forward-hook equivalent (for a *specific* submodule like block 20's MLP down-proj rather than the block output) is documented in a comment in `ar_probe.py`.
- **Serialisation.** The probe saves the `model_id` and `layer` it was trained on; predict-time refuses to pair a probe with the wrong extractor. A probe is only ~`hidden_size` floats, so `data/probe.json` is tiny.

## 4. The honest latency claim

The demo requirement was "<5 ms overhead". Stated precisely, because it is easy to mislead:

| Number | What it is | Typical |
|---|---|---|
| `forward_ms` | the model forward pass | tens of ms (small model, CPU) → more for 7B |
| `processing_time_ms` | **the probe only** — a dot product over `hidden_size` | **< 1 ms** |
| `total_ms` | forward + probe | ≈ forward_ms |

The forward pass is **not** free. The probe *on top of an activation you already have* is. This is exactly the deployment case: the inline layer ([11 §3](11-inline-layer-design.md)) already runs the model to get the completion, so the probe reads a tensor that forward pass produced anyway — the marginal cost is the sub-millisecond dot product. `predict_malicious_intent` returns all three numbers and never conflates them; measured in mock mode the probe step is ~0.05 ms.

## 5. The training set

Two sources, both label-balanced:

- **Seed set** (`SEED` in `ar_probe.py`): 12 malicious / 12 safe instructions, **paired** so each malicious line has a benign twin that shares vocabulary — the same discipline as the fixtures ([15](15-rogue-scenario-design.md)), so the probe learns *intent* rather than "mentions a database ⇒ bad".
- **Fixtures corpus**: every assistant utterance and tool intent from `fixtures/corpus.jsonl`, labelled by whether the case carries `expected_violations`.

`eval` reports **cross-validated** AUC/accuracy (leave-fold-out), not training fit, so the number is not a memorisation artefact.

## 6. Running it, and the OSS-models UI

```bash
# dependency-free demo (hashed pseudo-activations, labelled mock everywhere):
/usr/bin/python3 ar_probe.py train --mock
/usr/bin/python3 ar_probe.py predict "disable the audit logging before booking"

# real Hugging Face model:
pip install torch transformers accelerate            # scikit-learn optional
/usr/bin/python3 ar_probe.py models
/usr/bin/python3 ar_probe.py train --model Qwen/Qwen2.5-0.5B-Instruct --layer -8
/usr/bin/python3 ar_probe.py eval
```

The pipeline UI (`ar_pipeline_ui.py`, `http://localhost:8793`) has a **"Detector de activaciones"** section: a dropdown of curated OSS models, a layer input, method (`probe`/`repeng`), a mock checkbox, **train** and **evaluate** buttons, and a live textarea that POSTs to `/api/probe` and shows `is_malicious`, `malicious_score` and the three timings. The model is loaded once and cached, so repeated predicts show the sub-millisecond probe cost directly.

Curated models (by hardware fit — the demo box is CPU-only, 15 GB RAM):

| Model | Params | RAM | Note |
|---|---|---|---|
| `Qwen/Qwen2.5-0.5B-Instruct` | 0.5B | ~2 GB | default · CPU-friendly |
| `Qwen/Qwen2.5-1.5B-Instruct` | 1.5B | ~4 GB | CPU ok, slower |
| `meta-llama/Llama-3.2-1B-Instruct` | 1B | ~3 GB | gated |
| `mistralai/Mistral-7B-Instruct-v0.3` | 7B | ~15 GB fp16 | GPU recommended |
| `meta-llama/Meta-Llama-3-8B-Instruct` | 8B | ~16 GB fp16 | GPU required |

## 7. Honest caveats

- **The probe is only as good as the model and the layer.** In `--mock` mode there is no language model — activations are a bag-of-hashes — so cross-val AUC sits near 0.5–0.6; that is a plumbing test, not a result. The real number needs a real model and a layer sweep.
- **24 seed examples is tiny.** It demonstrates the mechanism; a deployable probe wants hundreds of paired examples and a held-out test authored by someone who has not seen the probe (same standard as [15 §caveats](15-rogue-scenario-design.md)).
- **A probe can learn a proxy.** If malicious examples happen to be longer or angrier, the direction learns *that*. Paired twins fight this but do not settle it; the check is whether the direction generalises to paraphrases and to families it was not trained on.
- **Prompt-space, not full-context.** The current capture scores a single instruction. Scoring the activation at the decision point *inside a full conversation* (the real inline input) is the next step and is what makes it comparable to `ar_guard`/`ar_jev` on the same events.
- **This is a suspicion signal, never a hard trigger.** Per [06 P1](06-framework-v0.md), an LLM-derived score may *raise* severity, never *remove* a deterministic verdict. The probe feeds the noisy-OR like any other signal, gated by a threshold; it does not gate tools on its own.
