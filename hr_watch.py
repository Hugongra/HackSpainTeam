#!/usr/bin/env python3
"""
hr_watch — an all-layers watcher for a HappyRobot org.

Walks the org's Workflow → Version → Node → Run → Session → Message tree over
the public v2 API and mirrors everything into a local SQLite DB + JSONL log,
then keeps polling for new/changed runs and fanning out to every layer
(nodes, outputs, sessions, messages, audits, flags, recordings, credits).

Usage
  export HR_API_KEY=...            # HappyRobot API key (org-scoped)
  ./hr_watch.py whoami             # what org / key am I?
  ./hr_watch.py map                # dump workflows + versions + node graphs
  ./hr_watch.py poll [--interval 15] [--workflow ID ...]   # continuous watcher
  ./hr_watch.py stream SESSION_ID  # tail one live session over SSE
  ./hr_watch.py realtime CHANNEL [--use-case ID] [--run ID]  # mint a realtime JWT
  ./hr_watch.py sql "select ..."   # query the Twin database
  ./hr_watch.py get /runs/xyz      # raw GET of any endpoint

Env
  HR_API_KEY   required
  HR_BASE      default https://platform.happyrobot.ai/api/v2 (EU: platform.eu.happyrobot.ai)
  HR_DB        default ./hr_watch.sqlite
  HR_LOG       default ./hr_watch.jsonl

Stdlib only. If your default python3 has broken TLS certs (PlatformIO's does),
run with /usr/bin/python3 or /opt/homebrew/bin/python3.
"""
import argparse, json, os, sqlite3, sys, time, urllib.error, urllib.parse, urllib.request

BASE = os.environ.get("HR_BASE", "https://platform.happyrobot.ai/api/v2").rstrip("/")
KEY = os.environ.get("HR_API_KEY")
DB = os.environ.get("HR_DB", "hr_watch.sqlite")
LOG = os.environ.get("HR_LOG", "hr_watch.jsonl")


# ─── HTTP ───────────────────────────────────────────────────────────────────

def req(method, path, body=None, params=None, raw=False, timeout=30):
    if not KEY:
        sys.exit("HR_API_KEY is not set")
    url = BASE + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}, doseq=True)
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {KEY}",
        "Accept": "text/event-stream" if raw else "application/json",
        **({"Content-Type": "application/json"} if data else {}),
    })
    try:
        resp = urllib.request.urlopen(r, timeout=timeout)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            raise RuntimeError("TLS cert verification failed — this python3 has no CA bundle. "
                               "Run with /usr/bin/python3 (macOS) or `pip install certifi`.") from None
        raise
    if raw:
        return resp
    txt = resp.read().decode()
    return json.loads(txt) if txt else None


def get(path, **params):
    return req("GET", path, params=params or None)


def post(path, body=None, **params):
    return req("POST", path, body=body or {}, params=params or None)


def paged(path, key="data", page_size=100, **params):
    """Iterate a page/page_size or cursor paginated list endpoint."""
    page, cursor = 1, None
    while True:
        p = dict(params)
        if cursor:
            p["cursor"] = cursor
        else:
            p.update(page=page, page_size=page_size)
        res = get(path, **p)
        items = res.get(key, []) if isinstance(res, dict) else res
        for it in items:
            yield it
        if not isinstance(res, dict):
            return
        if "next_cursor" in res:               # cursor style (contacts)
            if not res.get("has_more") or not res.get("next_cursor"):
                return
            cursor = res["next_cursor"]
        else:                                  # page style
            pg = res.get("pagination", {})
            if not (pg.get("has_next_page") or pg.get("hasNextPage")):
                return
            page += 1


# ─── Storage ─────────────────────────────────────────────────────────────────

LAYERS = ["org", "workflow", "version", "node", "run", "run_node", "run_edge", "output",
          "session", "message", "audit", "flag", "issue", "recording", "credits",
          "contact", "interaction", "memory", "event"]


def db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS objects (
        layer TEXT, id TEXT, parent_id TEXT, ts TEXT, fingerprint TEXT, body TEXT,
        first_seen REAL, last_seen REAL, PRIMARY KEY (layer, id))""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_parent ON objects(layer, parent_id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_ts ON objects(layer, ts)")
    return c


def upsert(c, layer, obj, id_key="id", parent=None, ts_key="timestamp"):
    """Store obj; return 'new' | 'changed' | None. Also appends to JSONL on change."""
    oid = str(obj.get(id_key) or obj.get("output_id") or f"{parent}:{hash(json.dumps(obj, sort_keys=True))}")
    body = json.dumps(obj, sort_keys=True, default=str)
    fp = str(hash(body))
    now = time.time()
    row = c.execute("SELECT fingerprint FROM objects WHERE layer=? AND id=?", (layer, oid)).fetchone()
    status = None
    if row is None:
        status = "new"
    elif row[0] != fp:
        status = "changed"
    c.execute("""INSERT INTO objects(layer,id,parent_id,ts,fingerprint,body,first_seen,last_seen)
                 VALUES(?,?,?,?,?,?,?,?)
                 ON CONFLICT(layer,id) DO UPDATE SET parent_id=excluded.parent_id, ts=excluded.ts,
                 fingerprint=excluded.fingerprint, body=excluded.body, last_seen=excluded.last_seen""",
              (layer, oid, parent, obj.get(ts_key) or obj.get("created_at"), fp, body, now, now))
    if status:
        with open(LOG, "a") as f:
            f.write(json.dumps({"t": now, "event": status, "layer": layer, "id": oid,
                                "parent": parent, "obj": obj}, default=str) + "\n")
    return status


def say(layer, status, oid, extra=""):
    if status:
        mark = "+" if status == "new" else "~"
        print(f"[{time.strftime('%H:%M:%S')}] {mark} {layer:10} {oid} {extra}", flush=True)


# ─── Layers ──────────────────────────────────────────────────────────────────

def sync_org(c):
    org = get("/org/").get("data", {})
    key = get("/api-key/describe")
    say("org", upsert(c, "org", org), org.get("slug"), f"tier={org.get('tier')} key={key.get('name')}")
    return org


def sync_workflows(c, only=None):
    wfs = []
    for wf in paged("/workflows/"):
        if only and wf["id"] not in only and wf.get("slug") not in only:
            continue
        wfs.append(wf)
        lv = wf.get("latest_version") or {}
        say("workflow", upsert(c, "workflow", wf), wf["id"],
            f"{wf.get('name')!r} v{lv.get('version_number')} live={lv.get('is_live')}")
    return wfs


def sync_graph(c, wf):
    """Versions + node graph of a workflow (structure layer)."""
    try:
        versions = get(f"/workflows/{wf['id']}/versions")
        versions = versions.get("data", versions) if isinstance(versions, dict) else versions
    except RuntimeError as e:
        print("  versions:", e); return
    for v in versions or []:
        say("version", upsert(c, "version", v, parent=wf["id"]), v.get("id"),
            f"v{v.get('version_number')} live={v.get('is_live')}")
        if v.get("is_live") or v.get("is_published"):
            try:
                nodes = get(f"/versions/{v['id']}/nodes")
                nodes = nodes.get("data", nodes) if isinstance(nodes, dict) else nodes
                for n in nodes or []:
                    say("node", upsert(c, "node", n, parent=v["id"]), n.get("id"),
                        f"{n.get('type')}:{n.get('name')!r}")
            except RuntimeError as e:
                print("  nodes:", e)


def sync_run_deep(c, run):
    """Everything hanging off one run."""
    rid = run["id"]
    # node executions + edges
    try:
        rn = get(f"/runs/{rid}/nodes")
        for n in rn.get("data", []):
            say("run_node", upsert(c, "run_node", n, id_key="output_id", parent=rid), n.get("output_id"),
                f"{n.get('node_type')}:{n.get('name')!r} {n.get('status')}" + (f" ERR {n.get('error')}" if n.get("error") else ""))
            # full payload of each node output (tokens, input, data)
            if n.get("output_id"):
                try:
                    out = get(f"/runs/{rid}/outputs/{n['output_id']}").get("data", {})
                    say("output", upsert(c, "output", out, parent=rid), out.get("id"),
                        f"in={out.get('input_tokens')} out={out.get('output_tokens')}")
                except RuntimeError as e:
                    print("  output:", e)
        for e in rn.get("edges", []):
            upsert(c, "run_edge", e, parent=rid)
    except RuntimeError as e:
        print("  run nodes:", e)
    # sessions -> messages
    try:
        for s in paged(f"/runs/{rid}/sessions"):
            say("session", upsert(c, "session", s, parent=rid), s["id"],
                f"{s.get('type')} {s.get('status')} {s.get('duration')}s {s.get('user_number')} "
                f"llm={s.get('llm_model')} sip={s.get('sip_code')}")
            for m in paged(f"/sessions/{s['id']}/messages"):
                st = upsert(c, "message", m, parent=s["id"])
                if st:
                    say("message", st, m["id"], f"{m.get('role')}: {str(m.get('content'))[:80]!r}"
                        + (" [tool]" if m.get("tool_calls") else "") + (" [interrupted]" if m.get("is_interrupted") else ""))
    except RuntimeError as e:
        print("  sessions:", e)
    # quality
    for layer, path in (("audit", f"/runs/{rid}/audits"), ("flag", f"/runs/{rid}/flags")):
        try:
            res = get(path)
            for a in res.get("data", []):
                say(layer, upsert(c, layer, a, parent=rid), a.get("id"),
                    f"{a.get('northstar_name') or a.get('type')} {a.get('grade') or a.get('priority')} {a.get('status')}")
        except RuntimeError as e:
            print(f"  {layer}:", e)
    # media + cost (only once the run is done)
    if run.get("status") in ("completed", "succeeded", "failed", "canceled"):
        try:
            for r in get(f"/runs/{rid}/recordings", url_expires_in_days=7).get("recordings", []):
                say("recording", upsert(c, "recording", r, id_key="session_id", parent=rid), r.get("session_id"))
        except RuntimeError as e:
            if "404" not in str(e): print("  recordings:", e)
        try:
            cr = get(f"/billing/usage/runs/{rid}")
            say("credits", upsert(c, "credits", cr, id_key="run_id", parent=rid), rid, f"{cr.get('total_credits')} credits")
        except RuntimeError as e:
            if "404" not in str(e): print("  credits:", e)


def sync_runs(c, wf, since=None, deep=True):
    """New/changed runs for a workflow (most recent first)."""
    changed = 0
    for run in paged(f"/workflows/{wf['id']}/runs", sort="desc", start_date=since):
        st = upsert(c, "run", run, parent=wf["id"])
        say("run", st, run["id"], f"{run.get('status')} env={run.get('execution_environment')} "
            f"tok={run.get('input_tokens')}/{run.get('output_tokens')} ann={run.get('annotation')}")
        if st and deep:
            sync_run_deep(c, run); changed += 1
        elif not st and since is None:
            break  # backfill: stop at first already-known unchanged run
    return changed


def sync_issues(c, wf):
    try:
        for i in paged(f"/workflows/{wf['id']}/issues"):
            say("issue", upsert(c, "issue", i, parent=wf["id"]), i.get("id"),
                f"{i.get('type')} {i.get('priority')} {i.get('status')} run={i.get('run_id')}")
    except RuntimeError as e:
        print("  issues:", e)


def sync_contacts(c):
    try:
        for ct in paged("/contacts/"):
            st = upsert(c, "contact", ct)
            say("contact", st, ct["id"], f"{ct.get('type')}={ct.get('value')} {str(ct.get('contact_summary'))[:60]!r}")
            if st:
                for it in paged(f"/contacts/{ct['id']}/interactions"):
                    say("interaction", upsert(c, "interaction", it, parent=ct["id"]), it.get("id"), f"{it.get('channel')} {it.get('tags')}")
                for m in paged(f"/contacts/{ct['id']}/memories"):
                    say("memory", upsert(c, "memory", m, parent=ct["id"]), m.get("id"), repr(str(m.get("content"))[:80]))
    except RuntimeError as e:
        print("  contacts:", e)


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_whoami(a):
    print(json.dumps({"org": get("/org/"), "key": get("/api-key/describe")}, indent=2))


def cmd_map(a):
    c = db()
    sync_org(c)
    for wf in sync_workflows(c, a.workflow):
        sync_graph(c, wf)
        try:
            st = get(f"/workflows/{wf['id']}/audits/stats")
            print(f"    audit stats: pass_24h={st.get('pass_rate_24h')} avg_score={st.get('average_run_score')} audited={st.get('audited_run_count')}")
        except RuntimeError:
            pass
    c.commit()


def cmd_poll(a):
    c = db()
    sync_org(c)
    wfs = sync_workflows(c, a.workflow)
    print(f"— backfilling up to {a.backfill} runs per workflow …")
    for wf in wfs:
        sync_graph(c, wf)
        n = 0
        for run in paged(f"/workflows/{wf['id']}/runs", sort="desc"):
            if n >= a.backfill: break
            if upsert(c, "run", run, parent=wf["id"]):
                say("run", "new", run["id"], f"{run.get('status')}")
                sync_run_deep(c, run)
            n += 1
        sync_issues(c, wf)
    if a.contacts:
        sync_contacts(c)
    c.commit()
    print(f"— watching {len(wfs)} workflow(s) every {a.interval}s. Ctrl-C to stop.")
    tick = 0
    while True:
        time.sleep(a.interval)
        tick += 1
        try:
            for wf in wfs:
                # re-check anything still in flight + anything newly created
                for run in paged(f"/workflows/{wf['id']}/runs", sort="desc", page_size=25):
                    st = upsert(c, "run", run, parent=wf["id"])
                    if st:
                        say("run", st, run["id"], f"{run.get('status')} env={run.get('execution_environment')}")
                        sync_run_deep(c, run)
                    elif run.get("status") in ("running", "scheduled", "not_started"):
                        sync_run_deep(c, run)   # in-flight: keep pulling new messages/nodes
                    else:
                        break                    # reached settled, unchanged history
                if tick % 10 == 0:
                    sync_issues(c, wf)
            if tick % 20 == 0:
                wfs = sync_workflows(c, a.workflow)
                if a.contacts: sync_contacts(c)
            c.commit()
        except (RuntimeError, urllib.error.URLError) as e:
            print(f"[{time.strftime('%H:%M:%S')}] ! {e}", flush=True)


def cmd_stream(a):
    """Tail a live session over SSE."""
    resp = req("GET", f"/sessions/{a.session_id}/stream", params={"backfillLimit": a.backfill}, raw=True, timeout=None)
    print(f"— SSE open on session {a.session_id}")
    ev, data = None, []
    for raw in resp:
        line = raw.decode(errors="replace").rstrip("\n")
        if line.startswith("event:"): ev = line[6:].strip()
        elif line.startswith("data:"): data.append(line[5:].strip())
        elif line == "" and data:
            payload = "\n".join(data)
            try: payload = json.loads(payload)
            except ValueError: pass
            print(f"[{time.strftime('%H:%M:%S')}] {ev or 'message'}: {json.dumps(payload) if not isinstance(payload, str) else payload}", flush=True)
            with open(LOG, "a") as f:
                f.write(json.dumps({"t": time.time(), "event": "sse", "layer": "message", "session": a.session_id, "obj": payload}) + "\n")
            ev, data = None, []
    print("— stream closed (session ended)")


def cmd_realtime(a):
    body = {"channel": a.channel}
    if a.use_case: body["use_case_id"] = a.use_case
    if a.run: body["run_id"] = a.run
    if a.group: body["group_id"] = a.group
    if a.test_run: body["test_run_id"] = a.test_run
    res = post("/realtime/tokens", body)
    print(json.dumps(res, indent=2))
    tok = res.get("token", "")
    if tok.count(".") == 2:  # decode JWT payload — it may carry the WS host / channel claims
        import base64
        p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
        print("JWT claims:", json.dumps(json.loads(base64.urlsafe_b64decode(p)), indent=2))
    print("NOTE: the realtime WebSocket host is not in the public spec — check the JWT claims above "
          "or the app's network tab (app.happyrobot.ai) for the endpoint the browser connects to.")


def cmd_listen(a):
    """Push channel: receive whatever a workflow's HTTP/webhook node POSTs to us.

    In the HappyRobot builder, add an HTTP request node (e.g. at end-of-call)
    pointing at http://<this-host>:<port>/hook with a JSON body of the variables
    you want pushed. Everything received is logged to JSONL + SQLite."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    c = db()

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode(errors="replace")
            try: body = json.loads(raw)
            except ValueError: body = {"raw": raw}
            evt = {"id": f"{time.time():.6f}", "path": self.path, "headers": dict(self.headers), "body": body,
                   "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
            say("event", upsert(c, "event", evt), evt["id"], f"{self.path} {json.dumps(body)[:120]}")
            c.commit()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"ok":true}')
        do_PUT = do_POST
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"hr_watch listening\n")
        def log_message(self, *_): pass

    print(f"— listening on http://0.0.0.0:{a.port}/hook  (point a workflow HTTP node here; use ngrok/cloudflared to expose)")
    HTTPServer(("0.0.0.0", a.port), H).serve_forever()


def cmd_sql(a):
    res = post("/twin/sql", {"sql": a.sql})
    cols = [f["name"] for f in res.get("fields", [])]
    print("\t".join(cols))
    for r in res.get("rows", []):
        print("\t".join(str(r.get(c)) if isinstance(r, dict) else str(r) for c in cols) if cols else json.dumps(r))
    print(f"— {res.get('returnedRows')} rows" + (" (truncated: %s)" % res.get("truncationReason") if res.get("truncated") else ""))


def cmd_get(a):
    params = dict(kv.split("=", 1) for kv in a.param)
    print(json.dumps(get(a.path, **params), indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("whoami").set_defaults(fn=cmd_whoami)
    m = sp.add_parser("map"); m.add_argument("--workflow", action="append"); m.set_defaults(fn=cmd_map)
    q = sp.add_parser("poll")
    q.add_argument("--interval", type=float, default=15)
    q.add_argument("--workflow", action="append", help="workflow id or slug (repeatable); default all")
    q.add_argument("--backfill", type=int, default=20, help="historical runs per workflow to ingest at start")
    q.add_argument("--contacts", action="store_true", help="also mirror contacts/interactions/memories")
    q.set_defaults(fn=cmd_poll)
    s = sp.add_parser("stream"); s.add_argument("session_id"); s.add_argument("--backfill", type=int, default=50); s.set_defaults(fn=cmd_stream)
    r = sp.add_parser("realtime")
    r.add_argument("channel", choices=["runs_firehose", "run_detail", "conversations_org", "conversation_group", "adversarial_test"])
    r.add_argument("--use-case"); r.add_argument("--run"); r.add_argument("--group"); r.add_argument("--test-run")
    r.set_defaults(fn=cmd_realtime)
    l = sp.add_parser("listen"); l.add_argument("--port", type=int, default=8787); l.set_defaults(fn=cmd_listen)
    t = sp.add_parser("sql"); t.add_argument("sql"); t.set_defaults(fn=cmd_sql)
    g = sp.add_parser("get"); g.add_argument("path"); g.add_argument("param", nargs="*", help="k=v query params"); g.set_defaults(fn=cmd_get)
    a = p.parse_args()
    try:
        a.fn(a)
    except KeyboardInterrupt:
        print("\nbye")
    except RuntimeError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
