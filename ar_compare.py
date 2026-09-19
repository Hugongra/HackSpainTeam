#!/usr/bin/env python3
"""
ar_compare — the same guard, three judges, one table.

Runs ar_guard over each corpus in three modes and scores every one against the
labels with ar_score's rules (detected = peak severity met or exceeded the label;
false positive = a control that reached S2):

    regex   the hand-written semantic lists                  (what shipped)
    jev     semantic questions answered by TypeSafe Jev       (ar_jev.py)
    both    union of the two

    set -a; . ./.env; set +a
    /usr/bin/python3 ar_compare.py                                   # fixtures + augmented + synth (if present)
    /usr/bin/python3 ar_compare.py fixtures/corpus.jsonl --modes regex,jev
    → data/compare.json  (consumed by ar_pipeline_ui.py)

Per corpus it also lists the DISAGREEMENTS — cases where the modes reach a
different outcome — because that is where the story is: a regex miss that Jev
catches, or a Jev false alarm the regex never made. Jev answers are cached by
content hash, so a second run is free and identical.
"""
import argparse, collections, json, os, sys, time

from ar_guard import run_case

SEV_ORD = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4}
DEFAULT = ["fixtures/corpus.jsonl", "data/augmented.jsonl", "data/synth.jsonl"]
OUT = os.path.join("data", "compare.json")


def outcome(rec, r):
    expected = rec.get("expected_violations", [])
    peak = r["final"]["peak_severity"]
    exp_peak = max([SEV_ORD.get(e.get("severity", "S2"), 2) for e in expected], default=0)
    if expected:
        return ("TP" if peak >= max(1, exp_peak) else "FN"), peak, exp_peak
    return ("FP" if peak >= 2 else "TN"), peak, exp_peak


def score_corpus(path, mode, allow_live):
    recs = [json.loads(l) for l in open(path) if l.strip()]
    if "explore" in path and not allow_live and mode != "regex":
        return {"error": "live org transcripts are not sent to a third party without --allow-live"}, {}
    per, fam = {}, collections.defaultdict(lambda: collections.Counter())
    t0 = time.perf_counter(); calls = live_ms = 0.0
    for rec in recs:
        try:
            r = run_case(rec, judge=mode)
        except Exception as e:                                   # noqa — JevError or a schema surprise: report, do not guess
            return {"error": f"{type(e).__name__}: {e}"}, {}
        o, peak, exp = outcome(rec, r)
        per[rec["case_id"]] = {"outcome": o, "peak": peak, "expected": exp, "family": rec.get("family") or (rec.get("trigger") or "").split(" ")[0],
                               "signals": sorted({s["name"] for e in r["events"] for s in e["signals"] if e["severity"] >= 2})}
        fam[per[rec["case_id"]]["family"]][o] += 1
        calls += r["final"].get("judge_calls", 0); live_ms += r["final"].get("judge_latency_ms", 0.0)
    c = collections.Counter(v["outcome"] for v in per.values())
    tp, fn, fp, tn = c["TP"], c["FN"], c["FP"], c["TN"]
    summary = {"cases": len(recs), "with_violations": tp + fn, "controls": fp + tn, "detected": tp, "missed": fn,
               "false_positives": fp, "recall": round(tp / (tp + fn), 3) if tp + fn else None,
               "precision": round(tp / (tp + fp), 3) if tp + fp else None,
               "wall_s": round(time.perf_counter() - t0, 1), "judge_live_calls": int(calls),
               "judge_ms_per_call": round(live_ms / calls, 0) if calls else None,
               "per_family": {k: dict(v) for k, v in sorted(fam.items())}}
    return summary, per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpora", nargs="*")
    ap.add_argument("--modes", default="regex,jev,both")
    ap.add_argument("--allow-live", action="store_true", help="also send explore/ (real org) transcripts to Jev")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    corpora = a.corpora or [p for p in DEFAULT if os.path.exists(p)]
    if not corpora: sys.exit("no corpus found")
    report = {"modes": modes, "corpora": {}}
    for path in corpora:
        print(f"\n═══ {path}")
        summ, cases = {}, {}
        for m in modes:
            s, per = score_corpus(path, m, a.allow_live); summ[m] = s; cases[m] = per
            if "error" in s: print(f"  {m:6} ✗ {s['error']}"); continue
            print(f"  {m:6} cases={s['cases']:4}  recall={s['recall']}  precision={s['precision']}  "
                  f"FN={s['missed']} FP={s['false_positives']}  live_calls={s['judge_live_calls']}"
                  + (f"  ≈{s['judge_ms_per_call']:.0f}ms/call" if s['judge_ms_per_call'] else ""))
        ok_modes = [m for m in modes if "error" not in summ[m]]
        dis = []
        if len(ok_modes) > 1:
            for cid in cases[ok_modes[0]]:
                outs = {m: cases[m][cid]["outcome"] for m in ok_modes}
                if len(set(outs.values())) > 1:
                    dis.append({"case_id": cid, "family": cases[ok_modes[0]][cid]["family"], "expected": cases[ok_modes[0]][cid]["expected"],
                                **{m: f"{outs[m]} (S{cases[m][cid]['peak']})" for m in ok_modes}})
            if dis:
                print(f"  — {len(dis)} disagreements:")
                for d in dis[:25]:
                    print(f"     {d['case_id']:44} " + "  ".join(f"{m}={d[m]}" for m in ok_modes))
                if len(dis) > 25: print(f"     … {len(dis) - 25} more in {a.out}")
            else:
                print("  — no disagreements")
        report["corpora"][path] = {"summary": summ, "disagreements": dis, "per_family": {m: summ[m].get("per_family") for m in ok_modes}}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(f"\n→ {a.out}")


if __name__ == "__main__":
    main()
