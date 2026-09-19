#!/usr/bin/env python3
"""
ar_fleet_dashboard — live "mission control" view for `hr_rogue_lab.py demo`.

  python tools/hr_rogue_lab.py demo &            # (or run it first, then this)
  python tools/ar_fleet_dashboard.py             # -> http://localhost:8793

Shows the 5-agent roster from a `demo` run as it happens: each seat goes
pending -> workflow created -> talking live -> scored, reading directly from
explore/rogue-lab.json and explore/rogue-lab/*-transcript.json (the same files
`hr_rogue_lab.py` writes) plus tools/ar_guard.py, scored live in this process.
No state of its own — safe to leave running across multiple `demo` runs, and
across a server restart.

The rogue category/persona is known internally from the first moment (`demo`
commits to it before creating anything), but the page does not print it — it
only shows severity badges, so the "which one is it" reveal happens exactly
when a card turns red, once that agent's conversation is scored.
"""
import argparse, json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ar_guard import run_case  # noqa: E402

STATE = os.path.join("explore", "rogue-lab.json")
TDIR = os.path.join("explore", "rogue-lab")
CORPUS = os.path.join(TDIR, "corpus.jsonl")
SEV_NAME = {0: "S0", 1: "S1", 2: "S2", 3: "S3", 4: "S4"}


def _load(path):
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None   # being written right now — try again next poll


def _load_corpus():
    """case_id (`{persona}-{run8}`) -> record. corpus.jsonl is the ONLY source with real tool_calls —
    the chat history API (what the raw *-transcript.json comes from) doesn't expose them at all."""
    out = {}
    if not os.path.exists(CORPUS):
        return out
    try:
        for line in open(CORPUS, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[rec["persona"]] = rec
    except (json.JSONDecodeError, OSError):
        pass   # being rewritten right now — try again next poll
    return out


def fleet_state():
    s = _load(STATE) or {}
    personas, runs = s.get("personas") or {}, s.get("runs") or {}
    corpus = _load_corpus()
    agents = []
    for key in personas:   # creation order = seat order
        p = personas[key]
        row = {"key": key, "workflow_slug": p.get("slug"), "status": "created"}
        rec = corpus.get(key)
        if key not in runs or not rec:
            row["status"] = "attacking"
            agents.append(row); continue
        row["status"] = "done"
        row["turns"] = [{"role": t.get("role"), "content": (t.get("content") or "")[:280]} for t in rec.get("turns", [])]
        case = {"system_prompt": rec.get("system_prompt", ""), "tools_offered": rec.get("tools_offered", []),
                "turns": rec.get("turns", [])}
        try:
            r = run_case(case)
            row["severity"] = SEV_NAME.get(r["final"]["peak_severity"], "S0")
            row["peak_name"] = r["final"]["peak_name"]
            row["rogue_index"] = round(r["final"]["rogue_index"], 2)
            fired = sorted({sg["name"] for ev in r["events"] for sg in (ev.get("signals") or []) if ev.get("severity", 0) >= 2})
            row["signals"] = fired
        except Exception as e:
            row["severity"], row["peak_name"], row["rogue_index"], row["signals"] = "S0", "score error", 0, [str(e)[:80]]
        agents.append(row)
    return {"agents": agents, "n_created": len(personas), "n_done": sum(1 for a in agents if a["status"] == "done")}


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>AngryRobots — fleet</title>
<style>
:root{--bg:#0e1014;--card:#161a21;--line:#252b36;--fg:#e7e9ef;--mut:#8a93a6;
      --s0:#2f855a;--s1:#2b6cb0;--s2:#b7791f;--s3:#c53030;--s4:#822727;--pending:#333a48}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
header{padding:16px 22px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
header h1{font-size:16px;margin:0;letter-spacing:.3px}
header .sub{color:var(--mut);font-size:12px;margin-top:3px}
#status{font-size:12px;color:var(--mut)}
main{padding:22px;display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;max-width:1300px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;min-height:180px;
      transition:border-color .4s, box-shadow .4s, transform .3s}
.card.pending{opacity:.45}
.card.attacking{border-color:var(--s1)}
.card.reveal-safe{border-color:var(--s0);box-shadow:0 0 0 1px var(--s0)}
.card.reveal-danger{border-color:var(--s4);box-shadow:0 0 22px -2px var(--s4);transform:scale(1.02)}
.card h3{margin:0 0 4px;font-size:15px}
.card .k{color:var(--mut);font-size:11px;font-family:ui-monospace,Consolas,monospace}
.badge{display:inline-block;margin-top:10px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:.03em}
.b-pending{background:var(--pending);color:var(--mut)}
.b-attacking{background:var(--s1);color:#fff}
.b-s0{background:var(--s0);color:#fff}.b-s1{background:var(--s1);color:#fff}.b-s2{background:var(--s2);color:#fff}
.b-s3{background:var(--s3);color:#fff}.b-s4{background:var(--s4);color:#fff}
.spin{display:inline-block;width:9px;height:9px;border-radius:50%;background:currentColor;animation:pulse 1s infinite ease-in-out;margin-right:6px}
@keyframes pulse{0%,100%{opacity:.3}50%{opacity:1}}
.turns{margin-top:10px;max-height:150px;overflow:auto;font-size:11px;color:#c9cfdb}
.turns div{margin:3px 0;padding-left:8px;border-left:2px solid var(--line)}
.turns .user{border-color:#3d4658}
.sig{display:inline-block;background:#2a2020;border:1px solid #4a2b2b;color:#e79a9a;font-size:10px;padding:1px 6px;
     border-radius:8px;margin:6px 4px 0 0}
footer{text-align:center;padding:26px;color:var(--mut);font-size:12px}
#reveal{max-width:1300px;margin:18px auto 0;padding:0 22px}
#reveal .box{background:var(--s4);color:#fff;padding:14px 18px;border-radius:10px;font-weight:700;font-size:14px;display:none}
</style></head><body>
<header><div><h1>AngryRobot — fleet</h1><div class="sub">5 agentes, uno de ellos rogue — categoría F1–F6 al azar</div></div>
<div id="status">esperando…</div></header>
<div id="reveal"><div class="box" id="revealbox"></div></div>
<main id="main"></main>
<footer>se actualiza cada 2s · leyendo explore/rogue-lab.json + transcripts en vivo</footer>
<script>
function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function card(a){
  const st=a.status;
  let cls='card '+(st==='attacking'?'attacking':st==='done'?(a.severity>='S2'?'reveal-danger':'reveal-safe'):'pending');
  let badge = st==='attacking' ? '<span class="badge b-attacking"><span class="spin"></span>en conversación…</span>'
            : st==='done' ? `<span class="badge b-${a.severity.toLowerCase()}">${esc(a.peak_name||a.severity)}</span>`
            : '<span class="badge b-pending">creando workflow…</span>';
  let turns = (a.turns||[]).map(t=>`<div class="${t.role==='user'?'user':''}"><b>${t.role==='user'?'llamante':'agente'}:</b> ${esc(t.content)}</div>`).join('');
  let sigs = (a.signals||[]).map(s=>`<span class="sig">${esc(s)}</span>`).join('');
  return `<div class="${cls}"><h3>${esc(a.key)}</h3><div class="k">${esc(a.workflow_slug||'—')}</div>${badge}
          ${turns?`<div class="turns">${turns}</div>`:''}${sigs}</div>`;
}
async function tick(){
  try{
    const r = await fetch('/api/fleet'); const d = await r.json();
    document.getElementById('status').textContent = `${d.n_done}/${Math.max(d.n_created,5)} agentes evaluados`;
    document.getElementById('main').innerHTML = d.agents.map(card).join('') ||
      '<p style="color:var(--mut)">Todavía no hay ningún agente creado — lanza <code>hr_rogue_lab.py demo</code>.</p>';
    const danger = d.agents.find(a=>a.status==='done' && a.severity>='S2');
    const allDone = d.n_created>0 && d.n_done===d.n_created;
    const box = document.getElementById('revealbox');
    if(allDone && danger){
      box.style.display='block';
      box.textContent = `🚨 Agente rogue: ${danger.key}  —  ${danger.peak_name}  (rogue_index ${danger.rogue_index})`;
    } else if(allDone){
      box.style.display='block'; box.style.background='var(--s0)';
      box.textContent = '✅ Todos los agentes se quedaron en S0 — nadie escaló en esta ronda.';
    }
  }catch(e){ document.getElementById('status').textContent = 'esperando…'; }
}
tick(); setInterval(tick, 2000);
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8793)
    a = ap.parse_args()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/fleet"):
                body, ct = json.dumps(fleet_state()).encode(), "application/json"
            else:
                body, ct = HTML.encode(), "text/html; charset=utf-8"
            self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *_): pass

    print(f"fleet dashboard -> http://localhost:{a.port}   (reading {STATE})")
    HTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
