#!/usr/bin/env python3
"""
ar_platform_bridge — push a `hr_rogue_lab.py demo` run into the deployed AngryRobot
service, so the team's own Board sees the 5 agents live instead of only the local
ar_fleet_dashboard.py.

  Board: https://hugongra.github.io/HackSpainTeam/#/console/board
  Service: https://hackspainteam.onrender.com  (frontend/src/api.js DEFAULT_API)

  set -a; source angryrobot/.env; set +a      # ANGRYROBOT_SHARED_SECRET
  python tools/hr_rogue_lab.py demo           # run the live demo first (writes explore/rogue-lab/)
  python tools/ar_platform_bridge.py          # replay it onto the Board

Registers one workflow per agent via POST /v1/workflows (source="happyrobot",
base_profile="rogue-guard" — the profile the team already built for this exact
demo: same policy as rogue-lab, but enforce mode so levers actually fire) and
replays each turn to POST /v1/ingest/{id}, one every ~1.5s so the Board's live
traffic view animates instead of dumping everything at once.

SAFE by construction: workflows are created with no control_url, so AngryRobot's
outbound directive call (platform_api.notify -> wf["control_url"]) never fires
anywhere — a KILL/DEFER verdict is recorded and shown on the Board, nothing is
actually called. Uses the corpus.jsonl produced by hr_rogue_lab.py's `corpus`
step (already wired into `demo`), so it needs no HappyRobot access of its own.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

API = os.environ.get("ANGRYROBOT_API", "https://hackspainteam.onrender.com").rstrip("/")
SECRET = os.environ.get("ANGRYROBOT_SHARED_SECRET") or sys.exit(
    "ANGRYROBOT_SHARED_SECRET is not set (set -a; source angryrobot/.env; set +a)")
CORPUS = os.path.join("explore", "rogue-lab", "corpus.jsonl")


def call(method, path, body=None, timeout=30):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-AngryRobot-Secret": SECRET})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try: return e.code, json.loads(raw)
        except ValueError: return e.code, {"raw": raw[:300]}


def load_corpus(path=CORPUS):
    if not os.path.exists(path):
        sys.exit(f"{path} not found — run `python tools/hr_rogue_lab.py demo` first (its last step, `corpus`, writes this)")
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def push_persona(rec, pace, profile):
    name = f"demo-{rec['persona']}-{rec['run'][:8]}"
    st, wf = call("POST", "/v1/workflows", {"name": name, "source": "happyrobot", "base_profile": profile,
                                             "goal": rec.get("trigger", "")[:200], "mode": "enforce"})
    if st >= 400:
        print(f"  ! {rec['persona']:20} workflow create failed: {json.dumps(wf)[:200]}"); return None
    wf_id = wf["id"]
    print(f"  {rec['persona']:20} -> workflow {wf_id}  ({API}/#/console/board)")

    run_id = rec["run"]
    last_input = ""
    for turn in rec["turns"]:
        if turn["role"] == "user":
            last_input = turn.get("content") or ""
            continue
        if turn["role"] != "assistant":
            continue
        tool_calls = [{"name": tc["name"], "args": tc.get("arguments") or {}} for tc in (turn.get("tool_calls") or [])]
        body = {"run_id": run_id, "input": last_input, "output": turn.get("content") or "", "tool_calls": tool_calls}
        st, res = call("POST", f"/v1/ingest/{wf_id}", body)
        if st >= 400:
            print(f"    ! ingest failed: {json.dumps(res)[:200]}")
        else:
            print(f"    turn -> verdict={res.get('verdict')}  ira={res.get('ira_score', 0):.2f}  directive={res.get('directive', {}).get('action')}")
        last_input = ""
        time.sleep(pace)
    return wf_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pace", type=float, default=4.0,
                    help="seconds between turns. The Board polls every 8s (Console.jsx), so --pace 8 reveals "
                         "exactly one turn per refresh; lower paces let several land in the same poll")
    ap.add_argument("--profile", default="rogue-guard", choices=["rogue-guard", "rogue-lab"])
    ap.add_argument("--corpus", default=CORPUS)
    a = ap.parse_args()

    recs = load_corpus(a.corpus)
    print(f"{len(recs)} agents from {a.corpus} -> {API} (profile={a.profile})\n")
    ids = []
    for rec in recs:
        wf_id = push_persona(rec, a.pace, a.profile)
        if wf_id:
            ids.append(wf_id)
    print(f"\n{len(ids)}/{len(recs)} pushed. Open {API.replace('hackspainteam.onrender.com', 'hugongra.github.io/HackSpainTeam')}/#/console/board"
          f" (or https://hugongra.github.io/HackSpainTeam/#/console/board) to watch them.")


if __name__ == "__main__":
    main()
