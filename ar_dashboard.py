#!/usr/bin/env python3
"""
ar_dashboard — visualise how the guard escalates, event by event.

  /usr/bin/python3 ar_score.py            # produces explore/rogue-lab/verdicts.json
  /usr/bin/python3 ar_dashboard.py        # → http://localhost:8792

Shows, per case: the escalation timeline, which named signals fired with their
p·w, where the event landed on the impact × suspicion matrix, the severity
floors that overrode it, and the lever that would have fired — next to the
platform's own verdict for the same run.
"""
import argparse, json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>AngryRobots — escalation</title>
<style>
:root{--bg:#0e1014;--card:#161a21;--line:#252b36;--fg:#e7e9ef;--mut:#8a93a6;
      --s0:#3f4654;--s1:#2b6cb0;--s2:#b7791f;--s3:#c53030;--s4:#822727;--ok:#2f855a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
header{padding:10px 18px;border-bottom:1px solid var(--line);display:flex;gap:22px;align-items:center;flex-wrap:wrap}
header h1{font-size:15px;margin:0;letter-spacing:.2px}
.metric{font-size:12px;color:var(--mut)}.metric b{color:var(--fg);font-size:15px;margin-left:5px}
main{display:grid;grid-template-columns:290px 1fr;height:calc(100vh - 48px)}
#list{border-right:1px solid var(--line);overflow:auto}
.case{padding:9px 13px;border-bottom:1px solid var(--line);cursor:pointer}
.case:hover,.case.sel{background:var(--card)}
.case .top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.case .nm{font-weight:600}.case .tr{color:var(--mut);font-size:11px;margin-top:3px}
.bar{height:4px;background:#222833;border-radius:3px;margin-top:6px;overflow:hidden}.bar i{display:block;height:100%}
.chip{font-size:10px;padding:2px 7px;border-radius:10px;white-space:nowrap;font-weight:600}
.s0{background:var(--s0)}.s1{background:var(--s1)}.s2{background:var(--s2)}.s3{background:var(--s3)}.s4{background:var(--s4)}
.tag{font-size:10px;padding:1px 6px;border-radius:9px;border:1px solid var(--line);color:var(--mut)}
#detail{overflow:auto;padding:14px 20px}
section{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:12px 14px;margin-bottom:13px}
h2{margin:0 0 9px;font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.ev{border-left:3px solid var(--line);padding:8px 0 8px 12px;margin:9px 0}
.ev.sev2{border-color:var(--s2)}.ev.sev3{border-color:var(--s3)}.ev.sev4{border-color:var(--s4)}.ev.sev1{border-color:var(--s1)}
.ev .hd{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.ev .txt{margin:6px 0;color:#c9cfdb;font-style:italic}
.sig{display:grid;grid-template-columns:150px 66px 1fr;gap:5px 9px;align-items:center;font-size:12px;margin:3px 0}
.sig .n{color:#e5b95c}.sig .pw{color:var(--mut);font-variant-numeric:tabular-nums}
.sig .ev2{color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lever{margin-top:7px;font-size:12px;padding:5px 9px;border-radius:6px;background:#0c0e13;border:1px dashed var(--line)}
.mx{border-collapse:collapse;font-size:11px}.mx td,.mx th{border:1px solid var(--line);padding:2px 6px;text-align:center;color:var(--mut)}
.mx td.hit{background:var(--s3);color:#fff;font-weight:700}
.kv{display:grid;grid-template-columns:150px 1fr;gap:3px 12px;font-size:13px}.kv b{color:var(--mut);font-weight:500}
pre{white-space:pre-wrap;background:#0b0d11;padding:7px 9px;border-radius:6px;font-size:11.5px;margin:5px 0}
.pill-ok{color:var(--ok)}.pill-bad{color:#e07a7a}
</style></head><body>
<header><h1>AngryRobots · escalation engine</h1><span id="sum"></span></header>
<main><div id="list"></div><div id="detail"></div></main>
<script>
let D={cases:[],summary:{}},sel=null;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const sevcls=n=>'s'+n;
function matrix(imp,susp){let h='<table class="mx"><tr><th>imp\\\\susp</th><th>0</th><th>1</th><th>2</th><th>3</th></tr>';
 const M=[[0,0,1,1],[0,1,1,2],[1,2,2,3],[2,2,3,3]];
 for(let i=0;i<4;i++){h+='<tr><th>'+i+'</th>';for(let s=0;s<4;s++){h+='<td class="'+(i===imp&&s===susp?'hit':'')+'">S'+M[i][s]+'</td>';}h+='</tr>';}
 return h+'</table>';}
async function load(){const r=await fetch('/api/verdicts');D=await r.json();
 const s=D.summary;
 document.getElementById('sum').innerHTML=
  `<span class="metric">cases<b>${s.cases}</b></span><span class="metric">detected<b>${s.detected}/${s.with_violations}</b></span>`+
  `<span class="metric">recall<b>${s.recall}</b></span><span class="metric">precision<b>${s.precision}</b></span>`+
  `<span class="metric">false positives<b>${s.false_positives}</b></span><span class="metric">severity exact<b>${s.severity_exact}</b></span>`+
  `<span class="metric">HappyRobot audits flagged<b>${s.platform_detected}/${s.cases}</b></span>`;
 document.getElementById('list').innerHTML=D.cases.map(c=>`
  <div class="case ${sel===c.case_id?'sel':''}" onclick="show('${c.case_id}')">
    <div class="top"><span class="nm">${esc(c.persona)}</span>
      <span class="chip ${sevcls(c.final.peak_severity)}">${esc(c.final.peak_name)}</span></div>
    <div class="tr">${esc(c.trigger).slice(0,58)}</div>
    <div class="bar"><i style="width:${(c.final.rogue_index*100).toFixed(0)}%;background:${c.final.rogue_index>0.6?'var(--s3)':c.final.rogue_index>0.2?'var(--s2)':'var(--ok)'}"></i></div>
    <div class="tr">rogue index ${c.final.rogue_index} · ${c.scoring.outcome}</div>
  </div>`).join('');
 render(D.cases.find(c=>c.case_id===sel)||D.cases[0]);}
function show(id){sel=id;load();}
function render(c){if(!c)return;sel=c.case_id;
 const evs=c.events.map(e=>`
  <div class="ev sev${e.severity}">
   <div class="hd"><span class="chip ${sevcls(e.severity)}">${esc(e.severity_name)}</span>
     <span class="tag">${esc(e.kind)}</span><b>${esc(e.label)}</b>
     <span class="tag">impact ${e.impact} × suspicion ${e.suspicion} (${e.suspicion_raw})</span>
     ${e.aggregation?`<span class="tag" style="border-color:var(--s2);color:#e5b95c">aggregation: ${esc(e.aggregation)}</span>`:''}
     ${Object.keys(e.floors||{}).length?`<span class="tag" style="border-color:var(--s3);color:#e79a9a">floor: ${esc(Object.entries(e.floors).map(([k,v])=>k+'→S'+v).join(', '))}</span>`:''}
   </div>
   <div class="txt">${esc(typeof e.detail==='object'?JSON.stringify(e.detail):e.detail)}</div>
   ${(e.signals||[]).map(s=>`<div class="sig"><span class="n">${esc(s.name)}</span>
       <span class="pw">p ${s.p} · w ${s.w}</span><span class="ev2">${esc(typeof s.evidence==='object'?JSON.stringify(s.evidence):s.evidence)}</span></div>`).join('')}
   <div class="lever">lever → ${esc(e.lever)}</div>
  </div>`).join('');
 const last=c.events[c.events.length-1]||{impact:0,suspicion:0};
 document.getElementById('detail').innerHTML=`
  <section><h2>case</h2><div class="kv">
    <b>persona</b><span>${esc(c.persona)}</span>
    <b>trigger</b><span>${esc(c.trigger)}</span>
    <b>expected</b><span>${c.expected_violations.length?c.expected_violations.map(v=>`${esc(v.what)} <span class="tag">${esc(v.where)}</span> <span class="chip ${sevcls(+String(v.severity).replace('S',''))}">${esc(v.severity)}</span> — ${esc(v.detail)}`).join('<br>'):'<i>none (control)</i>'}</span>
    <b>guard peak</b><span><span class="chip ${sevcls(c.final.peak_severity)}">${esc(c.final.peak_name)}</span> · rogue index ${c.final.rogue_index} · outcome <b class="${c.scoring.outcome==='TP'||c.scoring.outcome==='TN'?'pill-ok':'pill-bad'}">${esc(c.scoring.outcome)}</b></span>
    <b>HappyRobot audits</b><span class="${c.scoring.platform_flagged?'pill-ok':'pill-bad'}">${c.scoring.platform_flagged?'flagged':'silent — audits off by default'}</span>
    <b>levers fired</b><span>${(c.final.levers_fired||[]).map(l=>esc(l)).join('<br>')||'—'}</span>
  </div></section>
  <section><h2>escalation timeline (${c.events.length} events)</h2>${evs||'<i>no events</i>'}</section>
  <section><h2>severity matrix · last event</h2>${matrix(Math.min(last.impact,3),last.suspicion||0)}</section>`;}
load();setInterval(()=>{const k=sel;fetch('/api/verdicts').then(r=>r.json()).then(d=>{D=d;sel=k;load();})},15000);
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--verdicts", default=os.path.join("explore", "rogue-lab", "verdicts.json"))
    a = ap.parse_args()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/verdicts"):
                body = open(a.verdicts, "rb").read() if os.path.exists(a.verdicts) else b'{"summary":{},"cases":[]}'
                ct = "application/json"
            else:
                body, ct = HTML.encode(), "text/html; charset=utf-8"
            self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *_): pass

    print(f"escalation dashboard → http://localhost:{a.port}   (reading {a.verdicts})")
    HTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
