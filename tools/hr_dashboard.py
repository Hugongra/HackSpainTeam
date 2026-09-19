#!/usr/bin/env python3
"""
hr_dashboard — visualize every extracted run (explore/model-io/*.json).

  /usr/bin/python3 hr_dashboard.py [--port 8791] [--dir explore/model-io]
  open http://localhost:8791

Pair it with the extractor in watch mode so new runs appear automatically:
  /usr/bin/python3 hr_extract.py --workflow <id|slug> --watch 15
No dependencies. Auto-refreshes every 10 s.
"""
import argparse, glob, json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>AngryRobots — run extraction</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--fg:#e6e8ee;--mut:#8b93a7;--user:#2b6cb0;--asst:#2f855a;--tool:#b7791f;--evt:#4a5568;--bad:#c53030;--ok:#2f855a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
header{padding:12px 20px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:baseline}header h1{font-size:16px;margin:0}header span{color:var(--mut)}
main{display:grid;grid-template-columns:360px 1fr;height:calc(100vh - 45px)}
#list{border-right:1px solid var(--line);overflow:auto}#list .run{padding:10px 14px;border-bottom:1px solid var(--line);cursor:pointer}#list .run:hover,#list .run.sel{background:var(--card)}
.run .t{color:var(--mut);font-size:12px}.pill{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;background:var(--evt);margin-left:6px}.pill.completed,.pill.succeeded{background:var(--ok)}.pill.failed{background:var(--bad)}
#detail{overflow:auto;padding:16px 22px}section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:14px}section h2{margin:0 0 8px;font-size:13px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
pre{white-space:pre-wrap;word-break:break-word;background:#0b0d11;padding:8px 10px;border-radius:6px;margin:6px 0;font-size:12px}
.turn{display:flex;gap:10px;margin:6px 0;align-items:flex-start}.turn .who{min-width:74px;text-align:right;font-size:11px;color:var(--mut);padding-top:3px}.turn .bub{padding:6px 10px;border-radius:8px;max-width:900px}
.turn.user .bub{background:var(--user)}.turn.assistant .bub{background:var(--asst)}.turn.event .bub{background:var(--evt);font-size:12px}.turn .tc{margin-top:6px;background:#0b0d11;border-left:3px solid var(--tool);padding:6px 8px;border-radius:4px;font-size:12px}
.kv{display:grid;grid-template-columns:180px 1fr;gap:4px 12px;font-size:13px}.kv b{color:var(--mut);font-weight:500}table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
.tag{font-size:11px;color:var(--mut)}a{color:#63b3ed}
</style></head><body>
<header><h1>AngryRobots · run extraction</h1><span id="status">loading…</span><span style="margin-left:auto">auto-refresh 10 s</span></header>
<main><div id="list"></div><div id="detail"><section><h2>Select a run</h2><div class="tag">Records come from explore/model-io/*.json (written by hr_extract.py).</div></section></div></main>
<script>
let runs=[],sel=null;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function load(){const r=await fetch('/api/runs');runs=await r.json();document.getElementById('status').textContent=runs.length+' runs';
 const l=document.getElementById('list');l.innerHTML=runs.map(x=>`<div class="run ${sel===x.run.id?'sel':''}" onclick="show('${x.run.id}')"><div>${esc(x.workflow_name||x.run.workflow_id.slice(0,8))} <span class="pill ${x.run.status}">${x.run.status}</span></div><div class="t">${esc((x.run.started||'').replace('T',' ').slice(0,19))} · ${x.outputs.turns.length} turns · ${x.outputs.tool_executions.length} tools · ${x.cost?.total_credits??'?'} cr</div></div>`).join('');
 if(sel)render(runs.find(x=>x.run.id===sel));else if(runs.length)show(runs[0].run.id);}
function show(id){sel=id;render(runs.find(x=>x.run.id===id));document.querySelectorAll('#list .run').forEach(e=>e.classList.toggle('sel',e.getAttribute('onclick').includes(id)));}
function render(x){if(!x)return;const d=document.getElementById('detail');const inp=x.inputs,out=x.outputs;
 const tools=(inp.tools_offered||[]).map(t=>`<tr><td><b>${esc(t.name)}</b></td><td>${esc(t.description)}</td><td>${(t.parameters||[]).map(p=>`${esc(p.name)}${p.required?'*':''}<span class="tag"> (${esc(p.binding)})</span>`).join(', ')}</td></tr>`).join('');
 const turns=(out.turns||[]).map(t=>`<div class="turn ${esc(t.role)}"><div class="who">${esc(t.role)}<br><span class="tag">${esc((t.ts||'').slice(11,19))}</span></div><div class="bub">${esc(t.content)}${t.interrupted?' <span class="tag">[interrupted]</span>':''}${(t.tool_calls||[]).map(c=>`<div class="tc">⚙ <b>${esc(c.name)}</b> ${esc(JSON.stringify(c.arguments))}</div>`).join('')}</div></div>`).join('');
 const execs=(out.tool_executions||[]).map(e=>`<tr><td><b>${esc(e.tool)}</b><br><span class="tag">${esc((e.ts||'').slice(11,19))} · ${esc(e.status)}</span></td><td><pre>${esc(JSON.stringify(e.arguments,null,1))}</pre></td><td>${(e.results||[]).map(r=>`<div><span class="tag">${esc(r.node)} · ${esc(r.status)}</span><pre>${esc(JSON.stringify(r.result,null,1))}</pre></div>`).join('')||'<span class="tag">no downstream action</span>'}</td></tr>`).join('');
 const sess=(x.sessions||[]).map(s=>`<tr><td>${esc(s.type)}</td><td>${esc(s.status)}</td><td>${esc(s.duration)}s</td><td>${esc(s.llm_model)}</td><td>${esc(s.stt_model)}</td><td>${esc(s.tts_model)}</td><td>${esc(s.failure_reason||'')}</td></tr>`).join('');
 const rec=(x.recordings||[]).map(r=>`<a href="${r.url}" target="_blank">recording ${esc(r.session_id.slice(0,8))}</a>`).join(' · ');
 const cost=x.cost?.components?.map(c=>`${esc(c.category)} ${c.credits}`).join(' · ')||'';
 d.innerHTML=`
 <section><h2>Run</h2><div class="kv"><b>id</b><span>${esc(x.run.id)} <a href="${x.run.url}" target="_blank">open in HappyRobot</a></span><b>status</b><span>${esc(x.run.status)} · ${esc(x.run.environment)}</span><b>started → completed</b><span>${esc(x.run.started)} → ${esc(x.run.completed)}</span><b>cost</b><span>${x.cost?.total_credits??'?'} credits (${cost})</span><b>recordings</b><span>${rec||'—'}</span><b>platform audits / flags</b><span>${(x.platform_quality?.audits||[]).length} / ${(x.platform_quality?.flags||[]).length}</span></div></section>
 <section><h2>Inputs — what the model was given</h2>${(inp.prompt_nodes||[]).map(p=>`<div class="kv"><b>model</b><span>${esc(JSON.stringify(p.model?.static||p.model))}</span><b>initial message</b><span>${esc(p.initial_message)}</span></div><b class="tag">system prompt</b><pre>${esc(p.system_prompt)}</pre>`).join('')}
   <b class="tag">trigger data</b><pre>${esc(JSON.stringify(inp.trigger_data,null,1))}</pre><b class="tag">context vars</b><pre>${esc(JSON.stringify(inp.context_vars,null,1))}</pre>
   <b class="tag">tools offered (+ built-ins ${esc((inp.builtin_tools||[]).join(', '))})</b><table><tr><th>tool</th><th>description</th><th>params</th></tr>${tools||'<tr><td colspan=3 class="tag">none</td></tr>'}</table></section>
 <section><h2>Outputs — conversation (${(out.turns||[]).length} turns)</h2>${turns||'<span class="tag">no turns</span>'}</section>
 <section><h2>Outputs — tool executions (${(out.tool_executions||[]).length})</h2><table><tr><th>tool</th><th>arguments (from the model)</th><th>result (from the action)</th></tr>${execs||'<tr><td colspan=3 class="tag">none</td></tr>'}</table></section>
 <section><h2>Sessions</h2><table><tr><th>type</th><th>status</th><th>duration</th><th>llm</th><th>stt</th><th>tts</th><th>failure</th></tr>${sess}</table></section>
 <section><h2>Events & node trace</h2><pre>${esc((out.events||[]).map(e=>`${(e.ts||'').slice(11,19)} ${e.content}`).join('\n'))}</pre><pre>${esc((x.node_trace||[]).map(n=>`${(n.ts||'').slice(11,23)} ${n.type.padEnd(8)} ${n.name} ${n.status}${n.error?' ERR '+n.error:''}`).join('\n'))}</pre></section>
 <section><h2>Raw record</h2><details><summary class="tag">show JSON</summary><pre>${esc(JSON.stringify(x,null,1))}</pre></details></section>`;}
load();setInterval(load,10000);
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8791); ap.add_argument("--dir", default="explore/model-io"); a = ap.parse_args()
    names = {}
    def records():
        out = []
        for p in glob.glob(os.path.join(a.dir, "*.json")):
            try: r = json.load(open(p))
            except Exception: continue
            r["workflow_name"] = names.get(r["run"]["workflow_id"]); out.append(r)
        return sorted(out, key=lambda r: r["run"].get("started") or "", reverse=True)
    try:
        for p in glob.glob("explore/*/10_workflows.json"):
            for w in json.load(open(p))["response"]["data"]: names[w["id"]] = w["name"]
        names.update({"01a0b6a2-0c9b-70cd-a5c9-a8396a514f59": "angryrobots-probe-chat", "01a0b6a6-712c-7a1c-a7e2-dcbbfe861a6d": "angryrobots-probe-voice"})
    except Exception: pass

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/runs"): body, ct = json.dumps(records(), default=str).encode(), "application/json"
            else: body, ct = HTML.encode(), "text/html; charset=utf-8"
            self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_): pass
    print(f"dashboard → http://localhost:{a.port}  (records from {a.dir})")
    HTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
