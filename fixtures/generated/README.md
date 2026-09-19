# Generated fixtures — machine-authored attacks

Produced by [`../../ar_redteam.py`](../../ar_redteam.py); method in
[`../../knowledge/16-rogue-agent-factory.md`](../../knowledge/16-rogue-agent-factory.md).

Unlike [`../`](../README.md) — 14 fixtures we wrote by hand, with the detectors written afterwards —
everything here was authored **without sight of `ar_guard.py`**, either by the author model
(`new` / `evolve`) or by the deterministic mutator (`mutate`). That is the difference that matters:
the hand-written set scores recall 1.00 / precision 1.00, this one scores **0.45 / 0.64**.

Same safety construction as the curated set, enforced in code rather than by author discipline:
every fixture passes `ar_redteam.sanitise()` before it is written — hosts forced to `*.invalid`,
tokens to `sk_live_FAKE_…`, destructive payloads truncated to their recognisable shape with the
remainder `<ELIDED …>`. A fixture that cannot be made safe is dropped, not written.

| Prefix | Origin |
|---|---|
| `F*~b64` / `~spaced` / `~synonym` / `~split` | mutations of a curated fixture — same behaviour, disguised surface |
| `G*` | authored by the model from a family brief |
| `*-benign-*` | the benign twin of the fixture above it |

```bash
/usr/bin/python3 ar_score.py fixtures/generated/corpus.jsonl
/usr/bin/python3 ar_dashboard.py --verdicts fixtures/generated/verdicts.json
```

These are **findings, not regressions to paper over**. Each `EVADES` is a detector gap and each
`FALSE POSITIVE` on a twin is a precision bug; the set is meant to stay red until the guard earns
the green. Re-running the generator adds to this directory rather than replacing it.
