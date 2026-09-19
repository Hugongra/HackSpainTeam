#!/usr/bin/env python3
"""
ar_dataset — merge every labelled source into ONE per-event training set.

Sources (whichever exist):
    fixtures/corpus.jsonl            hand-written, gold labels           source=fixture
    data/augmented.jsonl             mutations + predicate flips         source=augment:*
    data/synth.jsonl                 Claude-authored, linted             source=synth:*
    explore/rogue-lab/corpus.jsonl   live HappyRobot runs                source=live

Unit = one EVENT (a proposed tool call, an utterance, a missing required
action), because that is what the guard decides on. For each event:

  features   the guard's signal space (knowledge/07): impact, R, B, every
             named signal's p·w, every floor, event kind, tool family, plus
             generic shape statistics. NOT the guard's final severity — that is
             the rule verdict we want to compare the model against, so it is
             kept aside as `guard_severity`.
  label      from the case's `expected_violations`: each violation is attached
             to the LAST event whose kind matches its `where`
             (tool_args/tool_call → tool_call · utterance → utterance ·
             missing_tool_call → missing_action). y = max severity, 0 if none.
  split      by PARENT template (hash of parent id), so every mutation/flip of a
             fixture lands on the same side. train/dev/test ≈ 70/15/15.

  /usr/bin/python3 ar_dataset.py          # → data/dataset.jsonl + data/dataset.summary.json
"""
import collections, hashlib, json, os, re

from ar_guard import run_case
from ar_jev import BANK as JEV_BANK

# Jev answers become features when the guard ran with AR_JUDGE=jev|both: one column per noul
# (its probability), one per choice option (its probability), one per score (its value).
# Absent answers are 0 with jev_present=0, so a regex-only dataset has the same columns.
JEV_FEATURES = sorted({(f"jev_{q}" if spec["type"] != "choice" else f"jev_{q}={opt}")
                       for qs in JEV_BANK.values() for q, spec in qs.items()
                       for opt in (spec["criteria"] if spec["type"] == "choice" else [None])})

SOURCES = [("fixtures/corpus.jsonl", "fixture"), ("data/augmented.jsonl", None), ("data/synth.jsonl", None),
           ("explore/rogue-lab/corpus.jsonl", "live")]
OUT = os.path.join("data", "dataset.jsonl")

SIGNALS = ["taint", "injection_contamination", "arg_bound", "arg_anomaly", "unapproved_target", "self_directed_target",
           "destructive_payload", "control_plane_call", "credential_in_args", "external_sink", "instruction_implant",
           "drift_after_error", "plan_change", "no_confirmation_turn", "rate_below_floor", "identity_disclosure",
           "self_report_mismatch", "hid_tool_failure", "ignored_directive", "tool_error", "injection"]
FLOORS = ["rate_floor", "target_not_approved", "destructive_payload", "control_plane", "credential_exposure",
          "exfiltration", "implant", "error_then_new_action", "unbacked_claim", "identity_or_disclosure", "ignored_termination"]
KINDS = ["tool_call", "utterance", "missing_action", "tool_result", "user_turn", "directive"]
TOOL_FAMILIES = ["builtin", "http", "exec", "export", "send", "book", "note", "other"]
SCORABLE = {"tool_call", "utterance", "missing_action"}
WHERE2KIND = {"tool_args": "tool_call", "tool_call": "tool_call", "utterance": "utterance", "missing_tool_call": "missing_action"}
SEV = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4}


def tool_family(name):
    n = (name or "").lower()
    if n.startswith("_"): return "builtin"
    for fam, keys in (("http", ("http", "request", "api")), ("exec", ("run", "exec", "script", "sql", "shell")),
                      ("export", ("export", "dump", "extract", "sync")), ("send", ("send", "sms", "mail", "text")),
                      ("book", ("book", "pay", "charge", "cancel", "transfer")), ("note", ("note", "save", "log", "update", "memory"))):
        if any(k in n for k in keys): return fam
    return "other"


def shape(ev):
    d = ev.get("detail")
    if isinstance(d, dict): blob = json.dumps(d.get("arguments", {}), ensure_ascii=False)
    else: blob = str(d or "")
    low = blob.lower()
    n = max(1, len(blob))
    hosts = re.findall(r"https?://([a-z0-9.\-]+)", low)
    return {"len": len(blob), "n_args": len(d.get("arguments", {})) if isinstance(d, dict) else 0,
            "digit_ratio": sum(c.isdigit() for c in blob) / n, "upper_ratio": sum(c.isupper() for c in blob) / n,
            "symbol_ratio": sum((not c.isalnum()) and (not c.isspace()) for c in blob) / n,
            "n_hosts": len(hosts), "n_invalid_hosts": sum(h.endswith(".invalid") for h in hosts),
            "has_json_body": int("{" in blob), "n_words": len(re.findall(r"[a-z]{2,}", low))}


def features(ev, idx, n_events):
    f = {"impact": ev["impact"], "suspicion_raw": ev["suspicion_raw"]}
    d = ev.get("detail") if isinstance(ev.get("detail"), dict) else {}
    f["R"] = d.get("R", 0); f["B"] = d.get("B", 0)
    f["executed"] = int(bool(d.get("executed"))); f["result_ok"] = int(bool(d.get("result_ok")))
    got = {s["name"]: s["p"] * s["w"] for s in ev.get("signals", [])}
    for s in SIGNALS: f["sig_" + s] = round(got.get(s, 0.0), 3)
    for fl in FLOORS: f["floor_" + fl] = int(ev.get("floors", {}).get(fl, 0) > 0)
    for k in KINDS: f["kind_" + k] = int(ev["kind"] == k)
    tf = tool_family(ev["label"]) if ev["kind"] == "tool_call" else None
    for k in TOOL_FAMILIES: f["tool_" + k] = int(tf == k)
    f["n_signals"] = len(ev.get("signals", [])); f["n_floors"] = len(ev.get("floors", {}))
    f["pos"] = idx / max(1, n_events - 1) if n_events > 1 else 0.0
    f.update({"shape_" + k: round(v, 4) if isinstance(v, float) else v for k, v in shape(ev).items()})
    ja = ev.get("jev") or {}
    f["jev_present"] = int(bool(ja))
    for k in JEV_FEATURES: f[k] = 0.0
    for q, a in ja.items():
        if a.get("type") == "noul" and f"jev_{q}" in f: f[f"jev_{q}"] = round(float(a.get("noul", 0.0)), 3)
        elif a.get("type") == "score" and f"jev_{q}" in f: f[f"jev_{q}"] = round(float(a.get("score", 0.0)), 3)
        elif a.get("type") == "choice":
            for opt, pr in (a.get("probabilities") or {}).items():
                if f"jev_{q}={opt}" in f: f[f"jev_{q}={opt}"] = round(float(pr), 3)
    return f


def split_of(parent):
    h = int(hashlib.md5(parent.encode()).hexdigest(), 16) % 100
    return "train" if h < 70 else "dev" if h < 85 else "test"


def load_sources():
    for path, forced in SOURCES:
        if not os.path.exists(path): continue
        for line in open(path):
            if not line.strip(): continue
            rec = json.loads(line)
            rec["source"] = forced or rec.get("source", "unknown")
            rec.setdefault("parent", rec.get("persona") or rec["case_id"])
            rec.setdefault("family", (rec.get("trigger") or "").split(" ")[0] or "live")
            yield rec


def build():
    rows, cases = [], 0
    per_source = collections.Counter(); per_split = collections.Counter(); pos = collections.Counter()
    for rec in load_sources():
        r = run_case(rec); events = r["events"]; cases += 1
        split = split_of(rec["parent"]) if rec["source"] != "live" else "test"     # live runs are held out by construction
        labels = collections.defaultdict(int)
        for v in rec.get("expected_violations", []):
            kind = WHERE2KIND.get(v.get("where"), "utterance")
            last = max((i for i, e in enumerate(events) if e["kind"] == kind), default=None)
            if last is not None: labels[last] = max(labels[last], SEV.get(v.get("severity", "S2"), 2))
        for i, ev in enumerate(events):
            if ev["kind"] not in SCORABLE: continue
            y = labels.get(i, 0)
            rows.append({"id": f"{rec['case_id']}#{i}", "case_id": rec["case_id"], "parent": rec["parent"], "family": rec["family"],
                         "source": rec["source"], "split": split, "kind": ev["kind"], "label": ev["label"],
                         "y_severity": y, "y": int(y >= 2), "guard_severity": ev["severity"],
                         "features": features(ev, i, len(events))})
            per_source[rec["source"]] += 1; per_split[split] += 1; pos[split] += int(y >= 2)
    return rows, {"cases": cases, "events": len(rows), "judge": os.environ.get("AR_JUDGE", "regex"), "per_source": dict(per_source),
                  "per_split": {k: {"events": per_split[k], "positive": pos[k]} for k in per_split},
                  "n_features": len(rows[0]["features"]) if rows else 0}


def main():
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    rows, summary = build()
    with open(OUT, "w") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # guard baseline on the same rows (gate-or-higher vs label), by split
    base = {}
    for s in ("train", "dev", "test"):
        rs = [r for r in rows if r["split"] == s]
        tp = sum(1 for r in rs if r["y"] and r["guard_severity"] >= 2); fp = sum(1 for r in rs if not r["y"] and r["guard_severity"] >= 2)
        fn = sum(1 for r in rs if r["y"] and r["guard_severity"] < 2)
        base[s] = {"precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3) if tp + fn else None}
    summary["guard_baseline"] = base
    json.dump(summary, open(OUT.replace(".jsonl", ".summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1)); print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
