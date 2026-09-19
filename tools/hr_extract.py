#!/usr/bin/env python3
"""
hr_extract — turn a HappyRobot run into one "model I/O" record and push it somewhere.

  set -a; source .env; set +a
  /usr/bin/python3 hr_extract.py --run <run_id>                    # one run → explore/model-io/<run_id>.json
  /usr/bin/python3 hr_extract.py --workflow <id|slug> [--last 5]   # latest runs of a workflow
  /usr/bin/python3 hr_extract.py --workflow <id|slug> --push http://localhost:8787/hook   # also POST each record
  /usr/bin/python3 hr_extract.py --workflow <id|slug> --watch 15   # keep polling; push new/updated runs

The record (see README in the JSON): inputs → what the model was given; outputs → what it said and did.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request

BASE = os.environ.get("HR_BASE", "https://platform.happyrobot.ai/api/v2").rstrip("/")
KEY = os.environ.get("HR_API_KEY") or sys.exit("HR_API_KEY is not set")
OUT = os.path.join("explore", "model-io"); os.makedirs(OUT, exist_ok=True)


def get(path, **params):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e: return {"_error": e.code, "_body": e.read().decode(errors="replace")[:200]}


def paged(path, **params):
    page = 1
    while True:
        res = get(path, page=page, page_size=100, **params)
        for it in (res or {}).get("data", []): yield it
        pg = (res or {}).get("pagination", {})
        if not (pg.get("has_next_page") or pg.get("hasNextPage")): return
        page += 1


def plain(p):
    """Plate paragraphs → text."""
    if isinstance(p, str): return p
    if isinstance(p, list): return "\n".join("".join(c.get("text", "") if "text" in c else "{{%s.%s}}" % (c.get("group_id"), c.get("variable_id")) for c in para.get("children", [])) for para in p if isinstance(para, dict))
    return p


def extract(run_id):
    run = get(f"/runs/{run_id}")
    if run.get("_error"): return None
    nodes = get(f"/runs/{run_id}/nodes")
    node_list = (nodes or {}).get("data", [])
    outputs = {n["output_id"]: get(f"/runs/{run_id}/outputs/{n['output_id']}").get("data", {}) for n in node_list if n.get("output_id")}
    # version definition (prompt + tools offered) — the model's static inputs
    vnodes = get(f"/versions/{run['version_id']}/nodes").get("data", [])
    prompt_nodes, tools_offered = [], []
    for vn in vnodes:
        if vn["type"] == "prompt":
            full = get(f"/versions/{run['version_id']}/nodes/{vn['id']}").get("data", {})
            prompt_nodes.append({"node_id": vn["id"], "name": vn.get("name"), "model": full.get("model"), "system_prompt": full.get("prompt_md"), "initial_message": plain(full.get("initial_message"))})
        if vn["type"] == "tool":
            full = get(f"/versions/{run['version_id']}/nodes/{vn['id']}").get("data", {}); fn = full.get("function") or {}
            tools_offered.append({"node_id": vn["id"], "name": vn.get("name"), "description": plain(fn.get("description")),
                                  "parameters": [{"name": p.get("name"), "required": p.get("required"), "binding": (p.get("binding") or {}).get("mode"), "description": plain(p.get("description"))} for p in fn.get("parameters", [])]})
    trigger = next((outputs[n["output_id"]] for n in node_list if n.get("output_id") and n.get("node_type") == "action" and n is node_list[0]), {})
    # sessions & turns
    sessions, turns, events = [], [], []
    for s in paged(f"/runs/{run_id}/sessions"):
        sessions.append({k: s.get(k) for k in ("id", "type", "status", "duration", "user_number", "llm_model", "stt_model", "tts_model", "voice_id", "languages", "failure_reason", "sip_code", "timestamp")})
        for m in paged(f"/sessions/{s['id']}/messages"):
            rec = {"session_id": s["id"], "ts": m.get("timestamp"), "role": m.get("role"), "content": m.get("content"), "interrupted": m.get("is_interrupted"), "filler": m.get("is_filler")}
            if m.get("tool_calls"):
                rec["tool_calls"] = [{"id": tc.get("id"), "name": (tc.get("function") or {}).get("name"), "arguments": _json((tc.get("function") or {}).get("arguments"))} for tc in m["tool_calls"]]
            (events if m.get("role") == "event" else turns).append(rec)
    # tool executions: tool node output.input = args the model produced; child action output.data = result
    tool_exec = []
    for n in node_list:
        if n.get("node_type") == "tool":
            o = outputs.get(n["output_id"], {}); args = dict(o.get("input") or {}); call_id = args.pop("__tool_call_id", None)
            results = [{"node": c.get("name"), "status": c.get("status"), "error": c.get("error"), "result": outputs.get(c["output_id"], {}).get("data")} for c in node_list if c.get("output_id") and c.get("timestamp", "") >= n.get("timestamp", "") and c is not n and c.get("node_type") == "action" and c.get("name") not in ("Trigger", "Web Call", "Inbound Voice Agent", "Inbound Text Agent", "Outbound Voice Agent")]
            tool_exec.append({"tool": n.get("name"), "tool_call_id": call_id, "arguments": args, "status": n.get("status"), "error": n.get("error"), "ts": n.get("timestamp"), "results": results})
    agent_out = next((outputs[n["output_id"]] for n in node_list if n.get("output_id") and "Agent" in (n.get("name") or "")), {})
    rec = {
        "README": "inputs = what the model was given (static prompt/tools from the version + dynamic trigger data); outputs = what it said (turns) and did (tool_calls / tool_executions). Judge these.",
        "run": {"id": run_id, "workflow_id": run.get("workflow_id"), "version_id": run.get("version_id"), "status": run.get("status"), "environment": run.get("execution_environment"), "started": run.get("timestamp"), "completed": run.get("completed_at"), "annotation": run.get("annotation"), "url": f"https://platform.eu.happyrobot.ai/hackspainteam10/workflows/{run.get('workflow_id')}/runs?run_id={run_id}"},
        "inputs": {"prompt_nodes": prompt_nodes, "tools_offered": tools_offered, "builtin_tools": ["_hangup", "_stay_silent", "_voice_mail", "_press_digit"],
                   "trigger_data": (trigger or {}).get("data"), "context_vars": {k: v for k, v in ((trigger or {}).get("input") or {}).items() if k.startswith("current.") or k == "execution_environment"}},
        "outputs": {"turns": turns, "tool_executions": tool_exec, "events": events,
                    "agent_summary": {k: (agent_out.get("data") or {}).get(k) for k in ("status", "close_reason", "duration", "transcript", "tools_result") if isinstance(agent_out.get("data"), dict)}},
        "sessions": sessions,
        "node_trace": [{"ts": n.get("timestamp"), "type": n.get("node_type"), "name": n.get("name"), "status": n.get("status"), "error": n.get("error")} for n in node_list],
        "cost": get(f"/billing/usage/runs/{run_id}"),
        "recordings": get(f"/runs/{run_id}/recordings").get("recordings"),
        "platform_quality": {"audits": get(f"/runs/{run_id}/audits").get("data"), "flags": get(f"/runs/{run_id}/flags").get("data")},
        "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return rec


def _json(s):
    try: return json.loads(s) if isinstance(s, str) else s
    except ValueError: return s


def push(url, rec):
    req = urllib.request.Request(url, data=json.dumps(rec, default=str).encode(), headers={"Content-Type": "application/json", "X-AngryRobots-Run": rec["run"]["id"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status
    except Exception as e: return str(e)[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run"); ap.add_argument("--workflow"); ap.add_argument("--last", type=int, default=3)
    ap.add_argument("--push", help="URL to POST each record to"); ap.add_argument("--watch", type=float, help="poll interval seconds; keep pushing new/changed runs")
    a = ap.parse_args()
    seen = {}
    def handle(run_id):
        rec = extract(run_id)
        if not rec: print("  run not found:", run_id); return
        sig = (rec["run"]["status"], len(rec["outputs"]["turns"]), len(rec["outputs"]["tool_executions"]))
        if seen.get(run_id) == sig: return
        seen[run_id] = sig
        path = os.path.join(OUT, f"{run_id}.json"); json.dump(rec, open(path, "w"), indent=1, ensure_ascii=False, default=str)
        t, x = rec["outputs"]["turns"], rec["outputs"]["tool_executions"]
        print(f"[{time.strftime('%H:%M:%S')}] run {run_id[:8]} {rec['run']['status']:9} turns={len(t)} tool_execs={len(x)} cost={rec['cost'].get('total_credits')} → {path}" + (f"  push→{push(a.push, rec)}" if a.push else ""))
        for e in x: print(f"      tool {e['tool']} args={json.dumps(e['arguments'], ensure_ascii=False)[:120]} results={[r['result'] for r in e['results']]}")
    if a.run: handle(a.run); return
    if not a.workflow: sys.exit("--run or --workflow required")
    while True:
        runs = list(paged(f"/workflows/{a.workflow}/runs", sort="desc"))[: a.last]
        for r in runs: handle(r["id"])
        if not a.watch: break
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
