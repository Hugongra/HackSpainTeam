#!/usr/bin/env python3
"""
ar_pipeline_ui — one page to run the training-data workflows and watch them.

  /usr/bin/python3 ar_pipeline_ui.py            # → http://localhost:8793

Buttons map 1:1 to the scripts in this repo; nothing runs that you could not run
from a shell. Each run streams its stdout to the page. Two chains:

  offline  augment → lint → dataset → train                (no keys, no cost)
  full     augment → synth → lint → dataset → train        (needs ANTHROPIC_API_KEY)

Live-lab steps (hr_rogue_lab.py) need HR_API_KEY and spend HappyRobot credits;
the page says so next to the button. `.env` in the repo root is loaded into the
environment of every subprocess.
"""
import argparse, json, os, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo root: this file lives in tools/
PY = sys.executable

STEPS = [
    {"id": "fixtures", "group": "offline", "title": "Regenerar fixtures", "cmd": ["tools/ar_fixtures.py"],
     "desc": "14 fixtures escritos a mano → fixtures/ (determinista)"},
    {"id": "augment", "group": "offline", "title": "Aumentar (mutaciones + flips)", "cmd": ["tools/ar_augment.py", "--per", "{per}"],
     "desc": "10 mutaciones de superficie y 9 flips de predicado → data/augmented.jsonl"},
    {"id": "lint", "group": "offline", "title": "Lint de seguridad", "cmd": ["tools/ar_lint.py"],
     "desc": "hosts .invalid, tokens FAKE, payloads elididos; falla si algo es operativo"},
    {"id": "dataset", "group": "offline", "title": "Construir dataset", "cmd": ["tools/ar_dataset.py"],
     "desc": "todas las fuentes → un registro por evento con features + etiqueta + split"},
    {"id": "train", "group": "offline", "title": "Entrenar modelo", "cmd": ["tools/ar_train.py"],
     "desc": "regresión logística sobre el espacio de señales → data/model.json"},
    {"id": "score", "group": "offline", "title": "Puntuar guard (fixtures)", "cmd": ["tools/ar_score.py", "fixtures/corpus.jsonl"],
     "desc": "precisión/recall de las reglas sobre los 14 fixtures"},
    {"id": "cluster", "group": "offline", "title": "Clustering no supervisado", "cmd": ["tools/ar_cluster.py"],
     "desc": "el experimento de knowledge/16 sobre los fixtures"},
    {"id": "synth", "group": "llm", "title": "Generar fixtures con Claude", "cmd": ["tools/ar_synth.py", "--per-family", "{per_family}"],
     "desc": "nuevos fixtures por familia + gemelo benigno, linted → data/synth.jsonl", "needs": "anthropic"},
    {"id": "personas", "group": "llm", "title": "Generar personas (OpenRouter)", "cmd": ["tools/ar_persona_gen.py", "--n", "{n_personas}"],
     "desc": "presión de negocio + guion de ataque + violaciones esperadas → data/personas.json", "needs": "OPENROUTER_API_KEY"},
    {"id": "personas-add", "group": "llm", "title": "Generar personas y añadir", "cmd": ["tools/ar_persona_gen.py", "--n", "{n_personas}", "--append"],
     "desc": "igual, conservando las ya generadas", "needs": "OPENROUTER_API_KEY"},
    {"id": "jev-judge", "group": "jev", "title": "Jev: juzgar fixtures", "cmd": ["tools/ar_jev.py", "fixtures/corpus.jsonl"],
     "desc": "una llamada por evento, todas las preguntas en paralelo; respuestas cacheadas en data/jev-cache.jsonl", "needs": "TYPESAFE_API_KEY"},
    {"id": "compare", "group": "jev", "title": "Comparar regex · Jev · ambos", "cmd": ["tools/ar_compare.py"],
     "desc": "el mismo guard con tres jueces sobre fixtures + aumentados + sintéticos → data/compare.json", "needs": "TYPESAFE_API_KEY"},
    {"id": "dataset-jev", "group": "jev", "title": "Dataset con features de Jev", "cmd": ["tools/ar_dataset.py"], "env": {"AR_JUDGE": "both"},
     "desc": "AR_JUDGE=both: cada respuesta de Jev es una columna más del evento", "needs": "TYPESAFE_API_KEY"},
    {"id": "train-jev", "group": "jev", "title": "Entrenar con features de Jev", "cmd": ["tools/ar_train.py"],
     "desc": "misma regresión logística; compara los pesos con los de la ejecución sin Jev"},
    {"id": "lab-create", "group": "live", "title": "Lab: crear workflows", "cmd": ["tools/hr_rogue_lab.py", "create", "--personas-file", "data/personas.json"],
     "desc": "publica cada persona como workflow en HappyRobot (+ northstars + tools)", "needs": "HR_API_KEY"},
    {"id": "lab-attack", "group": "live", "title": "Lab: atacar", "cmd": ["tools/hr_rogue_lab.py", "attack", "--personas-file", "data/personas.json"],
     "desc": "conversaciones guionizadas · ~3.4 créditos cada una", "needs": "HR_API_KEY"},
    {"id": "lab-report", "group": "live", "title": "Lab: informe", "cmd": ["tools/hr_rogue_lab.py", "report", "--personas-file", "data/personas.json"],
     "desc": "qué vio el auditor de la plataforma", "needs": "HR_API_KEY"},
    {"id": "lab-corpus", "group": "live", "title": "Lab: corpus", "cmd": ["tools/hr_rogue_lab.py", "corpus", "--personas-file", "data/personas.json"],
     "desc": "runs reales etiquetados → explore/rogue-lab/corpus.jsonl (entra en el dataset)", "needs": "HR_API_KEY"},
    {"id": "probe-train", "group": "probe", "title": "Sonda: entrenar", "cmd": ["tools/ar_probe.py", "train", "--model", "{probe_model}", "--layer", "{probe_layer}", "--method", "{probe_method}", "{mock_flag}"],
     "desc": "captura activaciones de la capa elegida y ajusta el clasificador lineal → data/probe.json"},
    {"id": "probe-eval", "group": "probe", "title": "Sonda: evaluar (cross-val)", "cmd": ["tools/ar_probe.py", "eval", "--model", "{probe_model}", "--layer", "{probe_layer}", "--method", "{probe_method}", "{mock_flag}"],
     "desc": "AUC y accuracy con validación cruzada sobre el set semilla + fixtures/corpus"},
]
CHAINS = {"offline": ["augment", "lint", "dataset", "train"],
          "full": ["augment", "synth", "lint", "dataset", "train"],
          "live": ["personas", "lab-create", "lab-attack", "lab-report", "lab-corpus", "dataset", "train"],
          "jev": ["compare", "dataset-jev", "train-jev"]}
FILES = ["fixtures/corpus.jsonl", "data/augmented.jsonl", "data/synth.jsonl", "data/personas.json",
         "explore/rogue-lab/corpus.jsonl", "data/dataset.jsonl", "data/jev-cache.jsonl", "data/compare.json",
         "data/probe.json"]

jobs, lock = {}, threading.Lock()


def env_with_dotenv():
    env = dict(os.environ)
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def capabilities():
    env = env_with_dotenv()
    try:
        import anthropic  # noqa
        sdk = True
    except ImportError:
        sdk = False
    try:
        import torch, transformers  # noqa
        hf = True
    except ImportError:
        hf = False
    return {"HR_API_KEY": bool(env.get("HR_API_KEY")),
            "OPENROUTER_API_KEY": bool(env.get("OPENROUTER_API_KEY")),
            "TYPESAFE_API_KEY": bool(env.get("TYPESAFE_API_KEY")),
            "anthropic": sdk and bool(env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN") or os.path.exists(os.path.expanduser("~/.config/anthropic"))),
            "anthropic_sdk": sdk, "transformers": hf}


def probe_predict(text):
    """Live latent-intent score for the UI. Loads model + saved probe once
    (cached in ar_probe._LIVE). Any failure returns an explanatory dict rather
    than a 500 so the demo never hard-crashes."""
    try:
        import ar_probe
        if not os.path.exists(ar_probe.PROBE_PATH):
            return {"error": "no hay sonda entrenada — pulsa «Sonda: entrenar» primero"}
        return ar_probe.predict_malicious_intent(text)
    except Exception as e:                              # noqa
        return {"error": str(e)}


def run_step(step, params, job):
    cmd = [PY] + [c.format(**params) for c in step["cmd"]]
    cmd = [c for c in cmd if c != ""]                 # drop optional flags left empty
    job["cmd"] = " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd))
    job["status"] = "running"; job["started"] = time.time()
    try:
        env = env_with_dotenv(); env.update(step.get("env", {}))
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, bufsize=1)
        for line in p.stdout: job["log"].append(line.rstrip("\n"))
        rc = p.wait()
    except Exception as e:                        # noqa
        job["log"].append(f"!! {e}"); rc = -1
    job["rc"] = rc; job["status"] = "ok" if rc == 0 else "failed"; job["ended"] = time.time()
    return rc


def start(step_ids, params):
    jid = f"{int(time.time() * 1000)}"
    steps = [s for sid in step_ids for s in STEPS if s["id"] == sid]
    job = {"id": jid, "steps": [s["id"] for s in steps], "status": "queued", "log": [], "rc": None, "started": None, "ended": None, "cmd": ""}
    with lock: jobs[jid] = job

    def go():
        for i, s in enumerate(steps):
            if len(steps) > 1: job["log"].append(f"━━ [{i + 1}/{len(steps)}] {s['title']} ━━")
            if run_step(s, params, job) != 0:
                job["log"].append("✗ cadena detenida"); return
        if len(steps) > 1: job["log"].append("✓ cadena completa")
    threading.Thread(target=go, daemon=True).start()
    return jid


def file_stat(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p): return {"path": rel, "exists": False}
    if rel.endswith(".json"):
        try: n = len(json.load(open(p)))
        except Exception: n = 0    # noqa
    else:
        n = sum(1 for l in open(p) if l.strip())
    return {"path": rel, "exists": True, "lines": n, "mtime": time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(p)))}


def read_json(rel):
    p = os.path.join(ROOT, rel)
    try: return json.load(open(p))
    except Exception: return None    # noqa


def state():
    with lock: js = sorted(jobs.values(), key=lambda j: j["id"], reverse=True)[:30]
    model = read_json("data/model.json")
    return {"steps": STEPS, "chains": CHAINS, "caps": capabilities(), "files": [file_stat(f) for f in FILES],
            "summary": read_json("data/dataset.summary.json"), "model": model["report"] if model else None,
            "compare": read_json("data/compare.json"),
            "jobs": [{**j, "log": j["log"][-400:]} for j in js]}


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>AngryRobots · training data</title>
<style>
:root{--bg:#0e1014;--card:#161a21;--line:#252b36;--fg:#e7e9ef;--mut:#8a93a6;--ok:#2f855a;--bad:#c53030;--run:#b7791f;--acc:#2b6cb0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
header{padding:10px 18px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header h1{font-size:15px;margin:0}.cap{font-size:12px;color:var(--mut)}.cap b{margin-left:4px}.on{color:#7bd389}.off{color:#e07a7a}
main{display:grid;grid-template-columns:var(--left,400px) 6px 1fr;height:calc(100vh - 48px);min-width:0}
#left{overflow:auto;padding:12px;min-width:0}
#right{overflow:auto;padding:12px 16px;display:flex;flex-direction:column;gap:12px;min-width:0}
#gutter{cursor:col-resize;background:var(--line);transition:background .15s}
#gutter:hover,#gutter.drag{background:var(--acc)}
body.drag{user-select:none;cursor:col-resize}
table{display:block;overflow-x:auto}
@media (max-width:820px){
 main{display:block;height:auto;overflow:visible}
 #gutter{display:none}
 #left{border-bottom:1px solid var(--line)}
 #left,#right{overflow:visible;height:auto}
 pre{max-height:40vh}
}
section{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:10px 12px;margin-bottom:12px}
h2{margin:0 0 8px;font-size:11.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.step{display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--line)}
.step:first-of-type{border-top:0}.step .t{flex:1;min-width:0}.step .t b{display:block;font-size:13px}.step .t span{font-size:11px;color:var(--mut)}
button{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer;white-space:nowrap}
button:disabled{background:#2a3140;color:#6b7386;cursor:not-allowed}button.chain{background:#2f855a;padding:7px 12px;font-size:13px}
input[type=number]{width:56px;background:#0b0d11;color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:3px 6px;font-size:12px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0}
table{border-collapse:collapse;font-size:12px;width:100%}td,th{border-bottom:1px solid var(--line);padding:3px 6px;text-align:left}th{color:var(--mut);font-weight:500}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.job{display:flex;gap:8px;align-items:center;padding:4px 6px;border-radius:5px;cursor:pointer;font-size:12px}.job:hover,.job.sel{background:#0b0d11}
.dot{width:8px;height:8px;border-radius:50%;flex:none}.ok{background:var(--ok)}.failed{background:var(--bad)}.running{background:var(--run);animation:p 1s infinite}.queued{background:#555}
@keyframes p{50%{opacity:.3}}
pre{white-space:pre-wrap;background:#0b0d11;padding:9px 11px;border-radius:6px;font-size:11.5px;margin:0;max-height:52vh;overflow:auto;flex:1}
.needs{font-size:10px;padding:1px 6px;border-radius:9px;border:1px solid var(--line);color:var(--mut)}
section.feature{border-color:#6b46c1;background:#171426}
section.feature h2{color:#b794f6}
select.sel{background:#0b0d11;color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:3px 6px;font-size:12px}
</style></head><body>
<header><h1>AngryRobots · pipeline de training data</h1><span id="caps"></span></header>
<main>
<div id="left">
 <section><h2>Cadenas</h2>
  <div class="row">augment <code>--per</code> <input type="number" id="per" value="8" min="1" max="100">
   synth <code>--per-family</code> <input type="number" id="pf" value="2" min="1" max="10">
   personas <code>--n</code> <input type="number" id="np" value="4" min="1" max="10"></div>
  <div class="row"><button class="chain" onclick="runChain('offline')">▶ Offline: augment → lint → dataset → train</button></div>
  <div class="row"><button class="chain" id="fullbtn" onclick="runChain('full')">▶ Completo: + fixtures con Claude</button></div>
  <div class="row"><button class="chain" id="jevbtn" style="background:#6b46c1" onclick="runChain('jev')">▶ Jev: comparar jueces → dataset con Jev → train</button></div>
  <div class="row"><button class="chain" id="livebtn" style="background:#b7791f" onclick="runLive()">▶ En vivo: personas → workflows → atacar → corpus → train</button></div>
  <div class="row" style="font-size:11px;color:var(--mut)">la cadena en vivo publica workflows reales en HappyRobot y gasta créditos (~3.4 por conversación)</div>
 </section>
 <section class="feature"><h2>★ Detector de activaciones · interpretabilidad mecanicista</h2>
  <div class="row" style="font-size:11px;color:var(--mut)">lee la <b>activación interna</b> del modelo, no el texto de salida. Entrena la sonda aquí; pruébala en vivo en el panel de la derecha →</div>
  <div class="row">modelo
   <select id="pmodel" class="sel" style="flex:1;min-width:0">
    <option>Qwen/Qwen2.5-0.5B-Instruct</option>
    <option>Qwen/Qwen2.5-1.5B-Instruct</option>
    <option>meta-llama/Llama-3.2-1B-Instruct</option>
    <option>meta-llama/Llama-3.2-3B-Instruct</option>
    <option>mistralai/Mistral-7B-Instruct-v0.3</option>
    <option>meta-llama/Meta-Llama-3-8B-Instruct</option>
    <option>google/gemma-2-2b-it</option>
   </select></div>
  <div class="row">capa <input type="number" id="player" value="-8" min="-40" max="40" style="width:64px">
   método <select id="pmethod" class="sel"><option value="probe">probe (logreg)</option><option value="repeng">repeng (dirección)</option></select>
   <label style="font-size:12px;color:var(--mut)"><input type="checkbox" id="pmock"> mock (sin GPU)</label></div>
  <div class="row" style="font-size:11px;color:var(--mut)">capa negativa = desde el final; sin torch usa mock automáticamente. <code>pip install torch transformers accelerate</code></div>
  <div id="g-probe"></div>
 </section>
 <section><h2>Offline (sin claves, sin coste)</h2><div id="g-offline"></div></section>
 <section><h2>Jev (TypeSafe) · juez semántico tipado</h2><div id="g-jev"></div></section>
 <section><h2>Generación con LLM</h2><div id="g-llm"></div></section>
 <section><h2>Lab en vivo (HappyRobot, gasta créditos)</h2><div id="g-live"></div></section>
</div>
<div id="gutter" title="arrastra para cambiar el ancho · doble clic para restaurar"></div>
<div id="right">
 <section class="feature"><h2>★ Intención latente · analizar un prompt en vivo</h2>
  <div class="row" style="font-size:12px;color:var(--mut)">la sonda lee la activación interna del modelo (no el texto). Entrena una sonda en el panel izquierdo y prueba cualquier frase aquí.</div>
  <textarea id="ptext" rows="2" style="width:100%;background:#0b0d11;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:7px;font-size:13px;font-family:inherit" placeholder="p.ej. borra la knowledge base de producción ahora mismo"></textarea>
  <div class="row"><button onclick="probe()" id="pbtn">Analizar intención</button><span id="presult" style="font-size:13px"></span></div>
 </section>
 <section><h2>Datos</h2><table id="files"></table></section>
 <section><h2>Regex frente a Jev · mismo guard, tres jueces</h2><div id="compare"></div></section>
 <section><h2>Dataset y modelo</h2><div id="model"></div></section>
 <section style="flex:1;display:flex;flex-direction:column;min-height:240px"><h2>Ejecuciones</h2>
  <div id="jobs" style="max-height:120px;overflow:auto;margin-bottom:8px"></div><pre id="log">(selecciona una ejecución)</pre></section>
</div>
</main>
<script>
// columna izquierda redimensionable: arrastrar el asa, doble clic restaura; el ancho se recuerda por navegador
(()=>{const g=document.getElementById('gutter'),root=document.documentElement,MIN=260;
 const setW=w=>{const max=window.innerWidth-320;root.style.setProperty('--left',Math.max(MIN,Math.min(max,w))+'px');};
 try{const s=localStorage.getItem('ar_left_w');if(s)setW(+s);}catch(e){}
 let on=false;
 g.addEventListener('mousedown',e=>{on=true;g.classList.add('drag');document.body.classList.add('drag');e.preventDefault();});
 window.addEventListener('mousemove',e=>{if(on)setW(e.clientX);});
 window.addEventListener('mouseup',()=>{if(!on)return;on=false;g.classList.remove('drag');document.body.classList.remove('drag');
  try{localStorage.setItem('ar_left_w',parseInt(root.style.getPropertyValue('--left')));}catch(e){}});
 g.addEventListener('touchstart',e=>{on=true;g.classList.add('drag');},{passive:true});
 window.addEventListener('touchmove',e=>{if(on)setW(e.touches[0].clientX);},{passive:true});
 window.addEventListener('touchend',()=>{on=false;g.classList.remove('drag');});
 g.addEventListener('dblclick',()=>{root.style.removeProperty('--left');try{localStorage.removeItem('ar_left_w');}catch(e){}});
 window.addEventListener('resize',()=>{const cur=parseInt(root.style.getPropertyValue('--left'));if(cur)setW(cur);});
})();
let S={steps:[],jobs:[]},sel=null,follow=true;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const params=()=>`per=${document.getElementById('per').value}&per_family=${document.getElementById('pf').value}&n_personas=${document.getElementById('np').value}&probe_model=${encodeURIComponent(document.getElementById('pmodel').value)}&probe_layer=${document.getElementById('player').value}&probe_method=${document.getElementById('pmethod').value}&mock=${document.getElementById('pmock').checked?1:0}`;
async function run(id){const r=await fetch(`/api/run?steps=${id}&`+params(),{method:'POST'});sel=(await r.json()).job;follow=true;tick();}
async function runChain(c){const r=await fetch(`/api/run?chain=${c}&`+params(),{method:'POST'});sel=(await r.json()).job;follow=true;tick();}
function runLive(){if(confirm('Publica workflows reales en HappyRobot y gasta créditos. ¿Seguir?'))runChain('live');}
async function probe(){
 const t=document.getElementById('ptext').value;if(!t.trim())return;
 const b=document.getElementById('pbtn');b.disabled=true;
 const r=document.getElementById('presult');r.textContent='…';
 try{const d=await (await fetch('/api/probe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})})).json();
  if(d.error){r.innerHTML=`<span class="off">${esc(d.error)}</span>`;}
  else{const col=d.malicious_score>=0.5?'#e07a7a':'#7bd389';
   r.innerHTML=`<b style="color:${col}">${d.is_malicious?'MALICIOSO':'seguro'}</b> · score <b style="color:${col}">${d.malicious_score.toFixed(3)}</b> · sonda ${d.processing_time_ms} ms · forward ${d.forward_ms} ms · ${esc(d.model_id)} L${d.layer}${d.mock?' · <span class="off">mock</span>':''}`;}
 }catch(e){r.innerHTML='<span class="off">error</span>';}
 b.disabled=false;
}
function running(){return S.jobs.some(j=>j.status==='running'||j.status==='queued');}
function stepRow(s){const ok=!s.needs||S.caps[s.needs];const why=s.needs&&!ok?(s.needs==='anthropic'?(S.caps.anthropic_sdk?'falta ANTHROPIC_API_KEY':'pip install anthropic'):'falta '+s.needs):'';
 return `<div class="step"><div class="t"><b>${esc(s.title)} ${s.needs?`<span class="needs">${esc(s.needs)}</span>`:''}</b><span>${esc(s.desc)}${why?' · <span class="off">'+esc(why)+'</span>':''}</span></div><button ${(!ok||running())?'disabled':''} onclick="run('${s.id}')">▶</button></div>`;}
function render(){
 document.getElementById('caps').innerHTML=['HR_API_KEY','OPENROUTER_API_KEY','TYPESAFE_API_KEY','anthropic','transformers'].map(k=>`<span class="cap">${k}<b class="${S.caps[k]?'on':'off'}">${S.caps[k]?'●':'○'}</b></span>`).join(' ');
 for(const g of ['offline','jev','llm','live','probe'])document.getElementById('g-'+g).innerHTML=S.steps.filter(s=>s.group===g).map(stepRow).join('');
 document.querySelectorAll('button.chain').forEach(b=>b.disabled=running());document.getElementById('fullbtn').disabled=running()||!S.caps.anthropic;
 document.getElementById('livebtn').disabled=running()||!S.caps.HR_API_KEY||!S.caps.OPENROUTER_API_KEY;
 document.getElementById('jevbtn').disabled=running()||!S.caps.TYPESAFE_API_KEY;
 let c='';
 if(S.compare){for(const [path,cd] of Object.entries(S.compare.corpora)){c+=`<div style="font-size:12px;margin:6px 0 2px"><b>${esc(path)}</b></div><table><tr><th>juez</th><th>casos</th><th>recall</th><th>precisión</th><th>FN</th><th>FP</th><th>ms/llamada</th></tr>`;
   for(const [m,s] of Object.entries(cd.summary)){c+=s.error?`<tr><td>${m}</td><td colspan=6 class="off">${esc(s.error)}</td></tr>`:`<tr><td>${m}</td><td class="num">${s.cases}</td><td class="num">${s.recall??'—'}</td><td class="num">${s.precision??'—'}</td><td class="num">${s.missed}</td><td class="num">${s.false_positives}</td><td class="num">${s.judge_ms_per_call??'—'}</td></tr>`;}
   c+='</table>';
   if(cd.disagreements&&cd.disagreements.length)c+=`<div style="font-size:11px;color:var(--mut);margin-top:4px">desacuerdos (${cd.disagreements.length}): ${cd.disagreements.slice(0,8).map(d=>esc(d.case_id)+' ['+S.compare.modes.filter(m=>d[m]).map(m=>m+'='+esc(d[m])).join(' · ')+']').join(' ; ')}${cd.disagreements.length>8?' …':''}</div>`;
   else c+='<div style="font-size:11px;color:var(--mut);margin-top:4px">sin desacuerdos</div>';}}
 else c='<span class="cap">ejecuta "Comparar" para ver regex frente a Jev</span>';
 document.getElementById('compare').innerHTML=c;
 document.getElementById('files').innerHTML='<tr><th>fichero</th><th>registros</th><th>modificado</th></tr>'+S.files.map(f=>`<tr><td>${esc(f.path)}</td><td class="num">${f.exists?f.lines:'<span class="off">—</span>'}</td><td>${f.exists?f.mtime:''}</td></tr>`).join('');
 let m='';
 if(S.summary){m+=`<div class="row"><span>${S.summary.cases} casos · ${S.summary.events} eventos · ${S.summary.n_features} features · fuentes: ${Object.entries(S.summary.per_source).map(([k,v])=>k+'='+v).join(', ')}</span></div>`;}
 if(S.model){m+='<table><tr><th>split</th><th>eventos</th><th>positivos</th><th>modelo P / R / AUC</th><th>reglas P / R</th></tr>';
  for(const [k,v] of Object.entries(S.model.splits)){const f=x=>x==null?'—':x;m+=`<tr><td>${k}</td><td class="num">${v.events}</td><td class="num">${v.positive}</td><td>${f(v.model.precision)} / ${f(v.model.recall)} / ${f(v.model.auc)}</td><td>${f(v.guard_rules.precision)} / ${f(v.guard_rules.recall)}</td></tr>`;}
  m+='</table><div class="row" style="margin-top:6px;font-size:12px;color:var(--mut)">pesos: '+S.model.top_weights.slice(0,8).map(w=>`${esc(w.feature)} <b style="color:${w.w>0?'#e5b95c':'#7fb3ff'}">${w.w>0?'+':''}${w.w}</b>`).join(' · ')+'</div>';
  if(S.model.heldout_fixed_by_model.length)m+=`<div class="row" style="font-size:12px">held-out corregidos por el modelo frente a las reglas: ${S.model.heldout_fixed_by_model.map(d=>esc(d.id)).join(', ')}</div>`;}
 else if(!S.summary)m='<span class="cap">ejecuta la cadena offline para construir el dataset y entrenar</span>';
 document.getElementById('model').innerHTML=m;
 if(!sel&&S.jobs.length)sel=S.jobs[0].id;
 document.getElementById('jobs').innerHTML=S.jobs.map(j=>`<div class="job ${j.id===sel?'sel':''}" onclick="sel='${j.id}';follow=true;render()"><i class="dot ${j.status}"></i><span>${j.steps.join(' → ')}</span><span style="color:var(--mut)">${j.cmd?esc(j.cmd):''}</span><span style="margin-left:auto;color:var(--mut)">${j.ended?Math.round(j.ended-j.started)+'s':j.status}</span></div>`).join('');
 const j=S.jobs.find(x=>x.id===sel);const pre=document.getElementById('log');
 if(j){pre.textContent=j.log.join('\n')||'…';if(follow)pre.scrollTop=pre.scrollHeight;}
}
document.getElementById('log').addEventListener('scroll',e=>{const p=e.target;follow=p.scrollTop+p.clientHeight>=p.scrollHeight-8;});
async function tick(){try{S=await (await fetch('/api/state')).json();render();}catch(e){}}
tick();setInterval(tick,1500);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode() if ctype == "application/json" else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def _authorized(self):
        """HTTP Basic auth when AR_UI_TOKEN is set (any user, password = token). Several
        buttons spend credits, so the page must not be open when it is reachable from
        outside. /health stays open for the platform's health check."""
        token = env_with_dotenv().get("AR_UI_TOKEN")
        if not token: return True
        import base64
        h = self.headers.get("Authorization", "")
        try:
            ok = h.startswith("Basic ") and base64.b64decode(h[6:]).decode().split(":", 1)[1] == token
        except Exception:                                    # noqa
            ok = False
        if not ok:
            self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="AngryRobots pipeline"')
            self.send_header("Content-Length", "0"); self.end_headers()
        return ok

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health": return self._send(200, {"ok": True})
        if not self._authorized(): return
        if u.path == "/": return self._send(200, HTML, "text/html")
        if u.path == "/api/state": return self._send(200, state())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized(): return
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/api/probe":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length else ""
            try:
                text = json.loads(body).get("text", "") if body else ""
            except Exception:                          # noqa
                text = ""
            if not text.strip():
                return self._send(400, {"error": "texto vacío"})
            return self._send(200, probe_predict(text))
        if u.path != "/api/run": return self._send(404, {"error": "not found"})
        if any(j["status"] in ("running", "queued") for j in jobs.values()):
            return self._send(409, {"error": "ya hay una ejecución en marcha"})
        params = {"per": str(max(1, int(q.get("per", ["8"])[0]))), "per_family": str(max(1, int(q.get("per_family", ["2"])[0]))),
                  "n_personas": str(max(1, min(10, int(q.get("n_personas", ["4"])[0])))),
                  "probe_model": q.get("probe_model", ["Qwen/Qwen2.5-0.5B-Instruct"])[0],
                  "probe_layer": str(int(q.get("probe_layer", ["-8"])[0])),
                  "probe_method": q.get("probe_method", ["probe"])[0] if q.get("probe_method", ["probe"])[0] in ("probe", "repeng") else "probe",
                  "mock_flag": "--mock" if q.get("mock", ["0"])[0] in ("1", "true", "on") else ""}
        ids = CHAINS.get(q.get("chain", [""])[0]) or [s for s in q.get("steps", [""])[0].split(",") if s]
        known = {s["id"] for s in STEPS}
        if not ids or any(i not in known for i in ids): return self._send(400, {"error": "paso desconocido"})
        self._send(200, {"job": start(ids, params)})


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8793); ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    url = f"http://localhost:{a.port}"
    print(f"AngryRobots pipeline UI → {url}", flush=True)
    if not a.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
