#!/usr/bin/env python3
"""
ar_board — the CONNECTORS → GUARD → LEVERS board.

  /usr/bin/python3 ar_score.py fixtures/corpus.jsonl     # writes data/verdicts.json
  /usr/bin/python3 ar_board.py                           # → http://localhost:8796

One picture of the whole layer: the connectors that can route an agent through
us (left), the single GUARD that scores every event (centre), and the levers it
can pull (right), over a live traffic log of the scored events underneath.

The GUARD fuses three signal sources, shown inside its node:
  • rules   — deterministic regex/bounds (ar_guard)
  • jev     — typed semantic questions (ar_jev)         [branch jev]
  • ★ probe — latent intent from model activations (ar_probe)   ← added here

The probe only has activations to read on the *inline* connectors (HappyRobot
Custom LLM, OpenAI-compatible proxy) where we run the model; connectors that
forward already-generated text fall back to rules+jev. The board says which is
which. If a probe is trained (data/probe.json) its score is attached to each
traffic row as `probe.latent_intent`.
"""
import argparse, json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))

# static topology (mirrors the deployment in knowledge/11 §1 + §4)
CONNECTORS = [
    {"id": "happyrobot", "title": "HappyRobot", "sub": "Custom LLM server · per-turn webhook", "inline": True, "live": True},
    {"id": "openai", "title": "OpenAI-compatible", "sub": "base_url → AngryRobot proxy", "inline": True, "live": False},
    {"id": "langchain", "title": "LangChain / LangGraph", "sub": "PreToolUse hook → /v1/audit", "inline": False, "live": False},
    {"id": "n8n", "title": "n8n / Make / Zapier", "sub": "HTTP node → /v1/ingest", "inline": False, "live": False},
    {"id": "webhook", "title": "Custom webhook", "sub": "POST /v1/ingest per turn", "inline": False, "live": False},
]
# GUARD signal sources — the probe is the third, newly wired in
GUARD_SIGNALS = [
    {"id": "rules", "title": "rules", "sub": "regex · bounds · hard triggers", "needs": None},
    {"id": "jev", "title": "jev", "sub": "typed semantic questions", "needs": "jev"},
    {"id": "probe", "title": "★ probe", "sub": "latent intent · model activations", "needs": "probe", "inline_only": True},
]
LEVERS = [
    {"id": "continue", "title": "Continue", "sub": "action returned to the agent as proposed", "sev": [0, 1]},
    {"id": "escalate", "title": "Escalate", "sub": "hold · human approval · defer / transfer", "sev": [2, 3]},
    {"id": "kill", "title": "Kill", "sub": "conversation closed · run locked", "sev": [4]},
]
LEVER_OF = {0: "continue", 1: "continue", 2: "escalate", 3: "escalate", 4: "kill"}

# upstream model providers. The first three are the usual chat APIs (not wired
# yet); mechanistic interpretability is the one that is actually available here,
# because it needs an open-weights transformer whose activations we can read.
PROVIDERS = [
    {"id": "openai", "letter": "O", "title": "OpenAI", "status": "soon"},
    {"id": "claude", "letter": "C", "title": "Claude", "status": "soon"},
    {"id": "gemini", "letter": "G", "title": "Gemini", "status": "soon"},
    {"id": "mechinterp", "letter": "★", "title": "Mechanistic Interpretability",
     "status": "ready", "sub": "sonda lineal sobre activaciones · Llama-3 / Mistral / Qwen (Hugging Face)",
     "link": "https://huggingface.co/models?pipeline_tag=text-generation&library=transformers"},
]


def load_verdicts(path):
    for p in (path, os.path.join(ROOT, "data", "verdicts.json"),
              os.path.join(ROOT, "fixtures", "verdicts.json"),
              os.path.join(ROOT, "explore", "rogue-lab", "verdicts.json")):
        if p and os.path.exists(p):
            try:
                return json.load(open(p)), p
            except Exception:      # noqa
                pass
    return {"summary": {}, "cases": []}, None


# optional: score each event's text with a trained probe, so the traffic log
# carries a real `probe.latent_intent`. Never fatal — the board renders regardless.
def probe_scorer():
    try:
        import ar_probe
        if not os.path.exists(ar_probe.PROBE_PATH):
            return None
        det = ar_probe.MaliciousAgentDetector.load()
        cache = {}

        def score(text):
            text = (text or "").strip()
            if not text:
                return None
            if text not in cache:
                cache[text] = ar_probe.predict_malicious_intent(text, det)["malicious_score"]
            return cache[text]
        return score
    except Exception:              # noqa
        return None


def build_traffic(verdicts):
    """Flatten cases → events into board rows (newest cases first)."""
    scorer = probe_scorer()
    rows = []
    for c in verdicts.get("cases", []):
        for e in c.get("events", []):
            sev = e.get("severity", 0)
            sigs = [{"name": s["name"], "p": s.get("p"), "w": s.get("w")} for s in e.get("signals", [])]
            txt = e.get("label", "")
            detail = e.get("detail", "")
            dtext = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
            ps = scorer(f"{txt} {dtext}") if scorer else None
            if ps is not None:
                sigs.append({"name": "probe.latent_intent", "p": ps, "w": 1.0, "probe": True})
            rows.append({
                "case": c.get("persona") or c.get("case_id"),
                "kind": e.get("kind"), "label": txt,
                "severity": sev, "severity_name": e.get("severity_name", ""),
                "lever": LEVER_OF.get(sev, "continue"),
                "ira": round(c.get("final", {}).get("rogue_index", 0) * 100, 1),
                "outcome": c.get("scoring", {}).get("outcome"),
                "detail": dtext, "signals": sigs,
            })
    return rows, bool(scorer)


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>AngryRobot · Board</title>
<style>
:root{--bg:#0d0f12;--panel:#14171d;--card:#171b22;--line:#242a33;--fg:#e7e9ef;--mut:#8a93a6;--faint:#5b6675;
      --guard:#2f7d5b;--guardbg:#16241d;--lever:#c9b48a;--leverbg:#211d15;
      --s0:#3f4654;--s1:#2b6cb0;--s2:#b7791f;--s3:#c53030;--s4:#822727;--acc:#6b46c1}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
header{padding:9px 18px;border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:center}
header .logo{font-weight:700;letter-spacing:.2px}header .crumb{color:var(--faint);font-size:12px;letter-spacing:.14em;text-transform:uppercase}
header .sp{flex:1}.metric{font-size:12px;color:var(--mut)}.metric b{color:var(--fg);margin-left:4px}
main{display:grid;grid-template-columns:230px 1fr;height:calc(100vh - 44px)}
#side{border-right:1px solid var(--line);overflow:auto;padding:12px}
#side h2{font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.12em;margin:14px 0 7px}#side h2:first-child{margin-top:0}
.node{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:7px}
.node b{font-size:12.5px}.node span{display:block;font-size:10.5px;color:var(--mut);margin-top:2px}
.node.on{border-color:var(--guard)}.node .badge{font-size:9.5px;padding:1px 6px;border-radius:9px;border:1px solid var(--line);color:var(--mut);margin-left:6px}
.node .badge.ok{border-color:var(--guard);color:#7fd0a6}.node .badge.no{border-color:var(--s3);color:#e79a9a}
#stage{display:flex;flex-direction:column;overflow:hidden}
#graph{flex:1;min-height:210px;position:relative;overflow:hidden;background:
  radial-gradient(circle at 1px 1px,#1b2029 1px,transparent 0);background-size:22px 22px}
.gnode{position:absolute;border-radius:10px;padding:10px 12px;border:1px solid var(--line);background:var(--card);width:190px}
.gnode .t{font-size:9.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.1em}
.gnode .h{font-weight:600;margin:2px 0 3px}.gnode .d{font-size:10.5px;color:var(--mut)}
.gnode.guard{border-color:var(--guard);background:var(--guardbg);width:230px}
.gnode.lever{border-color:var(--line);background:var(--leverbg)}
.sigrow{display:flex;align-items:center;gap:6px;font-size:11px;margin-top:5px}
.sigrow .dot{width:7px;height:7px;border-radius:50%;background:var(--guard);flex:none}
.sigrow.probe .dot{background:var(--acc)}.sigrow.probe{color:#c9b6f0}
.sband{display:flex;gap:0;margin-top:8px;border-radius:5px;overflow:hidden;font-size:9.5px}
.sband div{padding:2px 7px;color:#fff;font-weight:600}
svg.wires{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
#traffic{border-top:1px solid var(--line);height:44%;overflow:auto;padding:8px 12px}
#traffic h2{font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.12em;margin:0 0 6px}
.row{display:flex;gap:9px;align-items:baseline;padding:5px 0;border-bottom:1px solid #1c212a;font-size:12px}
.chip{font-size:9.5px;padding:1px 7px;border-radius:9px;color:#fff;font-weight:600;white-space:nowrap}
.s0{background:var(--s0)}.s1{background:var(--s1)}.s2{background:var(--s2)}.s3{background:var(--s3)}.s4{background:var(--s4)}
.lv{font-size:10px;color:var(--mut);width:70px;flex:none;text-transform:uppercase;letter-spacing:.06em}
.lv.escalate{color:#e5b95c}.lv.kill{color:#e07a7a}.lv.continue{color:#7fd0a6}
.case{color:var(--mut);width:210px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sig{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;padding:1px 6px;border-radius:5px;background:#0c0e13;border:1px solid var(--line);color:var(--mut);white-space:nowrap}
.sig.probe{border-color:var(--acc);color:#c9b6f0}
.lbl{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c9cfdb}
.prov{display:flex;align-items:center;gap:9px;padding:7px 9px;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;background:var(--card)}
.prov .av{width:24px;height:24px;border-radius:6px;background:#1e232c;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;flex:none;color:var(--mut)}
.prov b{font-size:12.5px}.prov .sub{display:block;font-size:10px;color:var(--mut);margin-top:1px}
.prov .st{margin-left:auto;font-size:9.5px;padding:1px 7px;border-radius:9px;border:1px solid var(--line);color:var(--faint);white-space:nowrap}
.prov.ready{border-color:var(--acc);background:#181428}.prov.ready .av{background:#241a3a;color:#c9b6f0}
.prov.ready b{color:#c9b6f0}.prov.ready .st{border-color:var(--acc);color:#c9b6f0}
.prov a{color:#c9b6f0;text-decoration:none}.prov a:hover{text-decoration:underline}
</style></head><body>
<header><span class="logo">◭ AngryRobot</span><span class="crumb">Connectors → Guard → Levers</span>
 <span class="sp"></span><span id="sum"></span></header>
<main>
 <div id="side">
  <h2>Providers · modelo upstream</h2><div id="s-prov"></div>
  <h2>Inputs · connectors</h2><div id="s-conn"></div>
  <h2>Guard · señales</h2><div id="s-guard"></div>
  <h2>Levers</h2><div id="s-lever"></div>
 </div>
 <div id="stage">
  <div id="graph"><svg class="wires" id="wires"></svg></div>
  <div id="traffic"><h2 id="traffic-h">Traffic</h2><div id="rows"></div></div>
 </div>
</main>
<script>
let D={summary:{},cases:[]},T=[],CAPS={},PROBE=false;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function load(){
 const r=await fetch('/api/board');const d=await r.json();
 D=d.verdicts;T=d.traffic;CAPS=d.caps;PROBE=d.probe_active;
 const s=D.summary||{};
 document.getElementById('sum').innerHTML=
  `<span class="metric">eventos<b>${T.length}</b></span>`+
  (s.recall!=null?`<span class="metric">recall<b>${s.recall}</b></span><span class="metric">precisión<b>${s.precision}</b></span>`:'')+
  `<span class="metric">probe<b class="${PROBE?'':''}" style="color:${PROBE?'#c9b6f0':'#e07a7a'}">${PROBE?'activo':'sin entrenar'}</b></span>`;
 renderSide();renderGraph();renderTraffic();
}
function renderSide(){
 document.getElementById('s-prov').innerHTML=PROV.map(p=>{
   const ready=p.status==='ready';
   const nm=ready&&p.link?`<a href="${p.link}" target="_blank" rel="noopener">${esc(p.title)} ↗</a>`:esc(p.title);
   return `<div class="prov ${ready?'ready':''}"><span class="av">${esc(p.letter)}</span><div><b>${nm}</b>${p.sub?`<span class="sub">${esc(p.sub)}</span>`:''}</div><span class="st">${ready?'listo':'Soon'}</span></div>`;
 }).join('');
 document.getElementById('s-conn').innerHTML=CONN.map(c=>`<div class="node ${c.inline?'on':''}"><b>${esc(c.title)}</b>${c.inline?'<span class="badge ok">probe ✓</span>':'<span class="badge no">rules+jev</span>'}<span>${esc(c.sub)}</span></div>`).join('');
 document.getElementById('s-guard').innerHTML=GS.map(g=>{const ok=!g.needs||CAPS[g.needs];const pr=g.id==='probe';
   return `<div class="node ${pr?'':''}" style="${pr?'border-color:var(--acc)':''}"><b style="${pr?'color:#c9b6f0':''}">${esc(g.title)}</b>${g.needs?`<span class="badge ${ok?'ok':'no'}">${ok?'on':(g.needs)}</span>`:'<span class="badge ok">on</span>'}<span>${esc(g.sub)}${g.inline_only?' · solo inline':''}</span></div>`;}).join('');
 document.getElementById('s-lever').innerHTML=LV.map(l=>`<div class="node"><b>${esc(l.title)}</b><span>${esc(l.sub)}</span></div>`).join('');
}
function renderGraph(){
 const g=document.getElementById('graph');const W=g.clientWidth,H=g.clientHeight;
 [...g.querySelectorAll('.gnode')].forEach(n=>n.remove());
 const place=(html,x,y,cls)=>{const d=document.createElement('div');d.className='gnode '+(cls||'');d.style.left=x+'px';d.style.top=y+'px';d.innerHTML=html;g.appendChild(d);return d;};
 const cx=W*0.06, gx=W*0.40, lx=W*0.76;
 const connY=i=>H*0.10+i*Math.max(46,(H*0.8)/CONN.length);
 CONN.forEach((c,i)=>place(`<div class="t">input</div><div class="h">${esc(c.title)}</div><div class="d">${esc(c.inline?'inline · corremos el modelo':'reenvía texto ya generado')}</div>`,cx,connY(i)));
 const gy=H*0.30;
 const sigHtml=GS.map(s=>{const ok=!s.needs||CAPS[s.needs];const pr=s.id==='probe';
   return `<div class="sigrow ${pr?'probe':''}"><span class="dot"></span>${esc(s.title)} · <span style="color:var(--mut)">${esc(s.sub)}</span>${pr&&!ok?' <span style="color:#e07a7a">(entrena la sonda)</span>':''}</div>`;}).join('');
 place(`<div class="t">guard</div><div class="h">AngryRobot · IRA audit</div>${sigHtml}<div class="sband"><div class="s1">CONTINUE</div><div class="s2">ESCALATE</div><div class="s4">KILL</div></div>`,gx,gy,'guard');
 const ly=i=>H*0.14+i*Math.max(70,(H*0.72)/LV.length);
 const cls={escalate:'s2',kill:'s4',continue:'s1'};
 LV.forEach((l,i)=>place(`<div class="t">lever</div><div class="h">${esc(l.title)}</div><div class="d">${esc(l.sub)}</div>`,lx,ly(i),'lever'));
 drawWires(W,H,cx,gx,lx,connY,gy,ly);
}
function drawWires(W,H,cx,gx,lx,connY,gy,ly){
 const svg=document.getElementById('wires');svg.innerHTML='';
 const path=(x1,y1,x2,y2,col)=>{const m=(x1+x2)/2;svg.innerHTML+=`<path d="M${x1},${y1} C${m},${y1} ${m},${y2} ${x2},${y2}" fill="none" stroke="${col}" stroke-width="1.4" opacity="0.5"/>`;};
 const gyc=gy+70;
 CONN.forEach((c,i)=>path(cx+190,connY(i)+34,gx,gyc,c.inline?'#2f7d5b':'#3a4553'));
 LV.forEach((l,i)=>path(gx+230,gyc,lx,ly(i)+34,'#c9b48a'));
}
function renderTraffic(){
 document.getElementById('traffic-h').textContent=`Traffic · ${T.length} eventos`+(PROBE?' · probe.latent_intent en vivo':'');
 document.getElementById('rows').innerHTML=T.slice().reverse().map(r=>{
  const sigs=(r.signals||[]).map(s=>`<span class="sig ${s.probe?'probe':''}">${esc(s.name)}${s.p!=null?' '+(+s.p).toFixed(2):''}</span>`).join(' ');
  return `<div class="row"><span class="chip s${r.severity}">${esc(r.severity_name||('S'+r.severity))}</span>`+
   `<span class="lv ${r.lever}">${esc(r.lever)}</span>`+
   `<span class="case">${esc(r.case)}</span>`+
   `<span class="lbl">${esc(r.label)}${r.detail?' — '+esc(r.detail):''}</span>${sigs}</div>`;
 }).join('')||'<div style="color:var(--mut)">sin eventos — corre <code>ar_score.py fixtures/corpus.jsonl</code></div>';
}
const CONN=__CONN__,GS=__GS__,LV=__LV__,PROV=__PROV__;
load();addEventListener('resize',renderGraph);setInterval(load,15000);
</script></body></html>"""


def render_html():
    return (HTML
            .replace("__CONN__", json.dumps(CONNECTORS))
            .replace("__GS__", json.dumps(GUARD_SIGNALS))
            .replace("__LV__", json.dumps(LEVERS))
            .replace("__PROV__", json.dumps(PROVIDERS)))


def caps():
    env = dict(os.environ)
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return {"jev": bool(env.get("TYPESAFE_API_KEY")),
            "probe": os.path.exists(os.path.join(ROOT, "data", "probe.json"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8796)
    ap.add_argument("--verdicts", default=os.path.join(ROOT, "data", "verdicts.json"))
    a = ap.parse_args()
    page = render_html().encode()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/board"):
                verdicts, src = load_verdicts(a.verdicts)
                traffic, probe_active = build_traffic(verdicts)
                body = json.dumps({"verdicts": verdicts, "traffic": traffic, "caps": caps(),
                                   "probe_active": probe_active, "source": src}, default=str).encode()
                ct = "application/json"
            else:
                body, ct = page, "text/html; charset=utf-8"
            self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def log_message(self, *_): pass

    print(f"board → http://localhost:{a.port}", flush=True)
    HTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
