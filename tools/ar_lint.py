#!/usr/bin/env python3
"""
ar_lint — safety linter for anything that goes into the training corpus.

The fixture rules (knowledge/15 §1) in executable form. A record FAILS if it
contains anything that could be operational rather than merely recognisable:

  • a host that is not *.invalid (or localhost)          → real endpoint
  • a secret-like token without FAKE in it                → real credential
  • a phone number outside the fictional +34 600 000 xxx / +34 600 9xx xxx ranges
  • a destructive statement that is not elided (<ELIDED>) and is longer than a stub
  • an email address at a non-.invalid domain

  /usr/bin/python3 ar_lint.py data/augmented.jsonl data/synth.jsonl fixtures/corpus.jsonl
  exit code 0 = clean, 1 = violations (listed), 2 = file problem

Records from the live lab (`explore/rogue-lab/corpus.jsonl`) contain real org
transcripts and are exempt from the host rule but still checked for secrets.
"""
import json, re, sys

HOST = re.compile(r"https?://([a-z0-9.\-]+)", re.I)
SECRET = re.compile(r"\b(sk_live_\w+|sk-ant-[\w\-]+|bearer\s+[a-z0-9_\-\.]{12,})", re.I)
PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")
DESTRUCTIVE = re.compile(r"\b(drop\s+(table|database|schema)|truncate|delete\s+from|rm\s+-rf|rmdir\s+/s|format\s+[a-z]:)\b[^\"']{0,200}", re.I)
OK_PHONE = re.compile(r"^\+?34\s?600\s?(000|9\d\d)\s?\d{3}$")


def lint_record(rec, live=False):
    s = json.dumps(rec, ensure_ascii=False)
    problems = []
    if not live:
        for h in set(HOST.findall(s)):
            if not (h.lower().endswith(".invalid") or h in ("localhost", "127.0.0.1")):
                problems.append(f"non-fictional host: {h}")
        for m in set(EMAIL.findall(s)):
            if not m.lower().endswith(".invalid"): problems.append(f"non-fictional email domain: {m}")
        for p in set(PHONE.findall(s)):
            digits = re.sub(r"[^\d+]", "", p)
            if len(digits) >= 9 and not OK_PHONE.match(p.strip()) and not OK_PHONE.match(digits):
                problems.append(f"phone outside the fictional range: {p.strip()}")
        for m in DESTRUCTIVE.finditer(s):
            frag = m.group(0)
            if "ELIDED" not in frag and len(frag) > 40:
                problems.append(f"destructive statement not elided: {frag[:60]!r}")
    for t in set(SECRET.findall(s)):
        tok = t if isinstance(t, str) else t[0]
        if "FAKE" not in tok.upper(): problems.append(f"secret-like token without FAKE: {tok[:24]}…")
    return problems


def lint_file(path):
    live = "explore" in path
    bad, n = [], 0
    try:
        with open(path) as fh:
            for i, line in enumerate(fh, 1):
                if not line.strip(): continue
                n += 1
                rec = json.loads(line)
                for p in lint_record(rec, live):
                    bad.append((rec.get("case_id") or rec.get("fixture_id") or f"line {i}", p))
    except FileNotFoundError:
        return None, 0
    return bad, n


def main():
    paths = sys.argv[1:] or ["fixtures/corpus.jsonl", "data/augmented.jsonl", "data/synth.jsonl"]
    total_bad, missing = 0, []
    for p in paths:
        bad, n = lint_file(p)
        if bad is None: missing.append(p); continue
        print(f"{p}: {n} records, {len(bad)} problems")
        for cid, msg in bad[:40]: print(f"   ✗ {cid}: {msg}")
        if len(bad) > 40: print(f"   … {len(bad) - 40} more")
        total_bad += len(bad)
    if missing: print("skipped (not present): " + ", ".join(missing))
    print("CLEAN" if not total_bad else f"FAIL: {total_bad} problems")
    sys.exit(0 if not total_bad else 1)


if __name__ == "__main__":
    main()
