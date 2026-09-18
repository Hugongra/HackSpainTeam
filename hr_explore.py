#!/usr/bin/env python3
"""
hr_explore — first-contact battery against a HappyRobot org.

Runs every read-only request family we care about, saves each raw response
under ./explore/<timestamp>/<name>.json, and prints a compact "shape" summary
(keys, types, sample values with numbers/emails/phones redacted) so we can see
what data exists before designing anything on it.

  export HR_API_KEY=...
  /usr/bin/python3 hr_explore.py                 # whole org
  /usr/bin/python3 hr_explore.py --workflow SLUG # focus on one workflow
  /usr/bin/python3 hr_explore.py --deep 5        # follow 5 runs into nodes/outputs/sessions/messages

Read-only except: POST /realtime/tokens and POST /voice/tokens (mint tokens, no side effects
beyond token issuance) — both skipped with --no-tokens.
"""
import argparse, base64, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

BASE = os.environ.get("HR_BASE", "https://platform.happyrobot.ai/api/v2").rstrip("/")
KEY = os.environ.get("HR_API_KEY") or sys.exit("HR_API_KEY is not set")
OUT = os.path.join("explore", time.strftime("%Y%m%d-%H%M%S"))
os.makedirs(OUT, exist_ok=True)

REDACT = [(re.compile(r"\+?\d[\d\s().-]{7,}\d"), "<phone/num>"),
          (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>")]


def call(method, path, body=None, params=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {KEY}", "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {})})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None), round((time.time() - t) * 1000)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try: parsed = json.loads(raw)
        except ValueError: parsed = {"raw": raw[:500]}
        return e.code, parsed, round((time.time() - t) * 1000)
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            sys.exit("TLS cert failure: run with /usr/bin/python3 or pip install certifi")
        raise


def redact(v):
    if isinstance(v, str):
        for rx, rep in REDACT: v = rx.sub(rep, v)
        return v[:80]
    return v


def shape(obj, depth=0, maxdepth=3):
    """Compact type/keys summary of a JSON value."""
    pad = "  " * depth
    if isinstance(obj, dict):
        lines = []
        for k, v in list(obj.items())[:40]:
            if isinstance(v, (dict, list)) and depth < maxdepth:
                lines.append(f"{pad}{k}: {'{}' if isinstance(v, dict) else f'[{len(v)}]'}")
                lines.append(shape(v, depth + 1, maxdepth))
            else:
                lines.append(f"{pad}{k}: {type(v).__name__} = {redact(v)!r}" if not isinstance(v, (dict, list)) else f"{pad}{k}: {type(v).__name__}")
        return "\n".join(l for l in lines if l)
    if isinstance(obj, list):
        return shape(obj[0], depth, maxdepth) if obj else pad + "(empty)"
    return pad + f"{type(obj).__name__} = {redact(obj)!r}"


def step(name, method, path, body=None, params=None, quiet=False):
    status, data, ms = call(method, path, body, params)
    with open(os.path.join(OUT, name + ".json"), "w") as f:
        json.dump({"request": {"method": method, "path": path, "params": params, "body": body},
                   "status": status, "ms": ms, "response": data}, f, indent=1, default=str)
    n = ""
    if isinstance(data, dict):
        for k in ("data", "keys", "recordings", "rows", "useCases"):
            if isinstance(data.get(k), list): n = f" · {len(data[k])} items"
    print(f"\n=== {name}  {method} {path}  → {status} ({ms} ms){n}")
    if status >= 400:
        print("   ", json.dumps(data)[:300])
    elif not quiet:
        print(shape(data))
    return status, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", help="workflow id or slug to focus on")
    ap.add_argument("--deep", type=int, default=3, help="runs to follow into nodes/outputs/sessions/messages")
    ap.add_argument("--no-tokens", action="store_true")
    a = ap.parse_args()
    print(f"base={BASE}  out={OUT}")

    # ---- org / key ----
    step("00_api_key", "GET", "/api-key/describe")
    step("01_org", "GET", "/org/")
    step("02_members", "GET", "/org/members/")

    # ---- workflows & structure ----
    _, wfs = step("10_workflows", "GET", "/workflows/", params={"page_size": 100})
    wfs = (wfs or {}).get("data", []) if isinstance(wfs, dict) else []
    if a.workflow:
        wfs = [w for w in wfs if a.workflow in (w.get("id"), w.get("slug"))]
    step("11_templates", "GET", "/workflows/templates", quiet=True)
    step("12_folders", "GET", "/workflow-folders/", quiet=True)
    step("13_integrations", "GET", "/integrations/", params={"include_events": "true", "page_size": 100}, quiet=True)
    step("14_integration_categories", "GET", "/integrations/categories", quiet=True)
    step("15_mcp_servers", "GET", "/mcp/", quiet=True)
    step("16_phone_numbers", "GET", "/phone-numbers/", quiet=True)
    step("17_knowledge_bases", "GET", "/knowledge-bases/", quiet=True)
    step("18_voices", "GET", "/voices/", quiet=True)
    step("19_signal_keys", "GET", "/signals/keys")

    prompt_nodes = []
    for i, wf in enumerate(wfs[:10]):
        tag = f"2{i}_{wf.get('slug') or wf['id'][:8]}"
        _, detail = step(f"{tag}_workflow", "GET", f"/workflows/{wf['id']}")
        live = (detail or {}).get("live_version") or (detail or {}).get("latest_version") or {}
        step(f"{tag}_versions", "GET", f"/workflows/{wf['id']}/versions", quiet=True)
        step(f"{tag}_variables", "GET", f"/workflows/{wf['id']}/variables", quiet=True)
        step(f"{tag}_issues", "GET", f"/workflows/{wf['id']}/issues", quiet=True)
        step(f"{tag}_audit_stats", "GET", f"/workflows/{wf['id']}/audits/stats", quiet=True)
        step(f"{tag}_node_errors", "GET", f"/workflows/{wf['id']}/audits/node-errors", quiet=True)
        if live.get("id"):
            _, nodes = step(f"{tag}_nodes", "GET", f"/versions/{live['id']}/nodes")
            for n in (nodes or {}).get("data", []) if isinstance(nodes, dict) else (nodes or []):
                if n.get("type") == "prompt":
                    prompt_nodes.append((wf, live, n))
                    # full node incl. model config — this is where a Custom-LLM setting would show
                    step(f"{tag}_prompt_{n['id'][:8]}", "GET", f"/versions/{live['id']}/nodes/{n['id']}")
                    step(f"{tag}_prompt_{n['id'][:8]}_vars", "GET", f"/versions/{live['id']}/nodes/{n['id']}/available-vars", quiet=True)

    # ---- runs → deep dive ----
    for i, wf in enumerate(wfs[:10]):
        tag = f"3{i}_{wf.get('slug') or wf['id'][:8]}"
        _, runs = step(f"{tag}_runs", "GET", f"/workflows/{wf['id']}/runs", params={"page_size": 10, "sort": "desc"})
        for j, run in enumerate(((runs or {}).get("data") or [])[:a.deep]):
            rt = f"{tag}_run{j}_{run['id'][:8]}"
            step(f"{rt}", "GET", f"/runs/{run['id']}")
            _, rn = step(f"{rt}_nodes", "GET", f"/runs/{run['id']}/nodes")
            for k, node in enumerate(((rn or {}).get("data") or [])[:6]):
                if node.get("output_id"):
                    step(f"{rt}_out{k}_{node.get('node_type')}", "GET", f"/runs/{run['id']}/outputs/{node['output_id']}")
            _, sess = step(f"{rt}_sessions", "GET", f"/runs/{run['id']}/sessions")
            for s in ((sess or {}).get("data") or [])[:2]:
                step(f"{rt}_sess_{s['id'][:8]}_messages", "GET", f"/sessions/{s['id']}/messages", params={"page_size": 50})
            step(f"{rt}_audits", "GET", f"/runs/{run['id']}/audits", quiet=True)
            step(f"{rt}_flags", "GET", f"/runs/{run['id']}/flags", quiet=True)
            step(f"{rt}_recordings", "GET", f"/runs/{run['id']}/recordings", quiet=True)
            step(f"{rt}_credits", "GET", f"/billing/usage/runs/{run['id']}", quiet=True)

    # ---- contacts, twin, billing ----
    _, contacts = step("40_contacts", "GET", "/contacts/", params={"limit": 5})
    for c in ((contacts or {}).get("data") or [])[:1]:
        step(f"41_contact_{c['id'][:8]}_interactions", "GET", f"/contacts/{c['id']}/interactions", params={"limit": 5})
        step(f"42_contact_{c['id'][:8]}_memories", "GET", f"/contacts/{c['id']}/memories", params={"limit": 5})
    step("50_twin_schema", "GET", "/twin/schema")
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); start = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - 30 * 86400))
    step("60_billing_totals", "GET", "/billing/usage/totals", params={"start": start, "end": end})
    step("61_billing_credits", "GET", "/billing/usage/credits", quiet=True)

    # ---- tokens: what do they encode? ----
    if not a.no_tokens and wfs:
        wf = wfs[0]
        st, tok = step("70_realtime_token_firehose", "POST", "/realtime/tokens", body={"channel": "runs_firehose", "use_case_id": wf["id"]})
        t = (tok or {}).get("token", "")
        if st < 300 and t.count(".") == 2:
            p = t.split(".")[1]; p += "=" * (-len(p) % 4)
            claims = json.loads(base64.urlsafe_b64decode(p))
            print("    JWT claims:", json.dumps(claims)[:600])
            json.dump(claims, open(os.path.join(OUT, "70_realtime_token_claims.json"), "w"), indent=1)
        step("71_voice_token_new_call", "POST", "/voice/tokens/", body={"workflow_id": wf["id"], "ttl_seconds": 60})

    print(f"\nDone. Raw responses in {OUT}/  ({len(os.listdir(OUT))} files)")
    if prompt_nodes:
        print("\nPrompt nodes (sub-agents) found — candidates for Custom LLM routing:")
        for wf, live, n in prompt_nodes:
            print(f"  {wf.get('slug'):30} v{live.get('version_number')}  node={n['id']}  persistent={n.get('persistent_id')}  name={n.get('name')!r}  model={json.dumps(n.get('model'))[:80]}")


if __name__ == "__main__":
    main()
