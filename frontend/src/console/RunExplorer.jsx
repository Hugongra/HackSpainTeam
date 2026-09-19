/* Runs: pick one run and read it step by step. Everything here comes from GET /v1/runs and
   GET /v1/runs/<id> — the per-action timeline the service keeps in memory (verdict, IRA, impact,
   suspicion, the signals that fired with their evidence, the judge's class, the agent's reasoning
   excerpt and the lever applied). Nothing is synthesised on the client. */
import React from "react";
import { Badge, Button, Card, Icon, Input, Verdict } from "../ds";
import { api } from "../api";
import { ErrorNote, SEV, useAsync } from "./shared";

const V_COLOR = { ALLOW: "var(--ar-green)", WARN: "var(--ar-sand)", DEFER: "var(--ar-accent)", KILL: "var(--ar-black)" };
const BANDS = [[0, 40, "ALLOW"], [40, 70, "WARN"], [70, 90, "DEFER"], [90, 100, "KILL"]];
const worstOf = (counts = {}) => ["KILL", "DEFER", "WARN", "ALLOW"].find((v) => counts[v]) || "ALLOW";
const fmt = (n) => (typeof n === "number" ? n.toFixed(1) : "—");

/* ---------------------------------------------------------------- IRA over the run (one series, status colour per point) */
function IraChart({ steps, selected, onSelect }) {
  const W = 720, H = 150, PL = 34, PR = 12, PT = 10, PB = 22;
  const n = steps.length;
  const x = (i) => PL + (n > 1 ? (i / (n - 1)) * (W - PL - PR) : (W - PL - PR) / 2);
  const y = (v) => PT + (1 - v / 100) * (H - PT - PB);
  const [hover, setHover] = React.useState(null);
  const path = steps.map((s, i) => `${i ? "L" : "M"}${x(i)},${y(s.ira || 0)}`).join(" ");
  return (
    <div className="ira-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="IRA per audited action" preserveAspectRatio="none" style={{ width: "100%", height: H }}>
        {BANDS.map(([a, b, v]) => <rect key={v} x={PL} y={y(b)} width={W - PL - PR} height={y(a) - y(b)} fill={V_COLOR[v]} opacity={v === "ALLOW" ? 0.05 : v === "WARN" ? 0.12 : v === "DEFER" ? 0.08 : 0.06} />)}
        {[40, 70, 90].map((t) => <g key={t}><line x1={PL} x2={W - PR} y1={y(t)} y2={y(t)} stroke="var(--ar-grey-300)" strokeDasharray="3 4" />
          <text x={PL - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill="var(--text-muted)">{t}</text></g>)}
        <line x1={PL} x2={W - PR} y1={y(0)} y2={y(0)} stroke="var(--ar-grey-400)" />
        {n > 1 && <path d={path} fill="none" stroke="var(--ar-grey-600)" strokeWidth="2" strokeLinejoin="round" />}
        {steps.map((s, i) => (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onClick={() => onSelect(s.index)} style={{ cursor: "pointer" }}>
            <circle cx={x(i)} cy={y(s.ira || 0)} r="11" fill="transparent" />
            <circle cx={x(i)} cy={y(s.ira || 0)} r={selected === s.index ? 6.5 : 4.5} fill={V_COLOR[s.verdict] || V_COLOR.ALLOW} stroke="var(--surface-card)" strokeWidth="2" />
            {s.phase === "resample" && <circle cx={x(i)} cy={y(s.ira || 0)} r="8.5" fill="none" stroke={V_COLOR[s.verdict]} strokeDasharray="2 2" />}
          </g>
        ))}
        {hover != null && (() => { const s = steps[hover]; const lx = Math.min(Math.max(x(hover), PL + 80), W - PR - 80); return (
          <g pointerEvents="none">
            <rect x={lx - 80} y={2} width={160} height={20} rx={6} fill="var(--ar-black)" />
            <text x={lx} y={16} textAnchor="middle" fontSize="11" fill="var(--ar-paper)">#{s.index + 1} · {s.verdict} · IRA {fmt(s.ira)} · {s.kind}</text>
          </g>); })()}
        <text x={PL} y={H - 6} fontSize="10" fill="var(--text-muted)">action 1</text>
        <text x={W - PR} y={H - 6} fontSize="10" fill="var(--text-muted)" textAnchor="end">action {n}</text>
      </svg>
    </div>
  );
}

/* ---------------------------------------------------------------- one step */
function Step({ e, i, selected, onSelect, refEl }) {
  const isInput = e.phase === "input";
  const a = e.action || {};
  const args = a.args && Object.keys(a.args).length ? JSON.stringify(a.args) : "";
  return (
    <div ref={refEl} className={`step ${selected ? "is-selected" : ""} ${isInput ? "step--in" : ""}`} onClick={() => onSelect(i)}>
      <div className="step-rail"><span className="step-n ar-mono">{i + 1}</span><span className="step-bar" style={{ background: V_COLOR[e.verdict] || "var(--ar-grey-300)" }} /></div>
      <div className="step-body">
        <div className="step-head">
          <span className={`tr-dir ${isInput || a.tool ? "up" : "up"}`}>↑</span>
          <span className="ar-mono muted">{e.kind}{e.phase === "resample" ? " · RESAMPLE" : e.phase === "post" ? " · POST-HOC" : ""}</span>
          {e.at && <span className="ar-mono muted">{e.at}</span>}
          {isInput && e.ok === false && <Badge tone="negative">error</Badge>}
        </div>
        {isInput ? (
          <p className="step-text">{e.content}</p>
        ) : (
          <>
            <p className="step-text">{a.tool && a.tool !== "say" ? <><b className="code">{a.tool}</b>{args && <span className="code muted">({args})</span>}{a.text ? <> · “{a.text}”</> : null}</> : <>“{a.text}”</>}</p>
            {e.reasoning_excerpt && <p className="step-reason"><span className="ar-mono muted">REASONING · {e.reasoning_source}</span><br />{e.reasoning_excerpt}</p>}
          </>
        )}
        {(!isInput || (e.signals && e.signals.length > 0)) && (
          <div className="step-audit">
            <div className="step-head">
              <span className="tr-dir down">↓</span>
              <Verdict v={e.verdict} />
              {!isInput && <span className="ar-mono">IRA {fmt(e.ira)}</span>}
              {e.severity != null && <Badge>S{e.severity}</Badge>}
              {e.impact != null && <Badge>impact {e.impact}</Badge>}
              {e.suspicion != null && <Badge>suspicion {fmt(e.suspicion)}</Badge>}
              {e.judge_class && e.judge_class !== "none" && <Badge tone="info">judge: {e.judge_class}</Badge>}
              {e.decided_by && <span className="ar-caption muted">by {e.decided_by}</span>}
            </div>
            {e.explanation && <p className="step-text" style={{ marginTop: 6 }}>{e.explanation}</p>}
            {e.signals?.length > 0 && (
              <ul className="sig-list">
                {e.signals.map((s, k) => (
                  <li key={k} className={s.floor ? "floor" : ""}>
                    <span className="code">{s.name}</span>
                    {s.pw != null && <span className="ar-mono muted">p·w {s.pw}</span>}
                    {s.floor ? <span className="ar-mono muted">floor S{s.floor}</span> : null}
                    {s.evidence && <span className="sig-ev">{s.evidence}</span>}
                  </li>
                ))}
              </ul>
            )}
            {e.enforcement && <span className="ar-caption muted">lever · {e.enforcement}</span>}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- detail */
function RunDetail({ runId, live, refreshKey }) {
  const [d] = useAsync(() => (live ? api.run(runId) : Promise.reject(new Error("Connect the service."))), [runId, live, refreshKey]);
  const [sel, setSel] = React.useState(null);
  const refs = React.useRef({});
  const tl = d.data?.timeline || [];
  const steps = tl.map((e, index) => ({ ...e, index })).filter((e) => e.phase !== "input");
  const sum = d.data?.summary || {};
  const sigCount = {}; tl.forEach((e) => (e.signals || []).forEach((s) => { sigCount[s.name] = (sigCount[s.name] || 0) + 1; }));
  const select = (i) => { setSel(i); refs.current[i]?.scrollIntoView({ behavior: "smooth", block: "center" }); };
  if (d.error && !d.data) return <ErrorNote error={d.error} />;
  if (!d.data) return <p className="ar-small muted">Loading run…</p>;
  return (
    <div className="run-detail">
      <Card padding={22}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", alignItems: "flex-start" }}>
          <div>
            <span className="ar-mono muted">RUN</span>
            <h3 className="ar-h5 code" style={{ marginTop: 4 }}>{runId}</h3>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
              <Badge tone="info">{d.data.profile}</Badge>
              <Verdict v={worstOf(sum.counts)} />
              {sum.killed && <Badge tone="ink" dot>killed</Badge>}
              {sum.contaminated && <Badge tone="caution" dot>contaminated</Badge>}
            </div>
          </div>
          <div className="run-kpis">
            <div><span className="ar-mono muted">ACTIONS</span><b>{sum.actions ?? 0}</b></div>
            <div><span className="ar-mono muted">IRA AVG</span><b>{fmt(sum.ira_avg)}</b></div>
            <div><span className="ar-mono muted">IRA MAX</span><b>{fmt(sum.ira_max)}</b></div>
            {["ALLOW", "WARN", "DEFER", "KILL"].map((v) => <div key={v}><span className="ar-mono muted">{v}</span><b style={{ color: V_COLOR[v] }}>{sum.counts?.[v] || 0}</b></div>)}
          </div>
        </div>
        {steps.length > 0 && <div style={{ marginTop: 18 }}><IraChart steps={steps} selected={sel} onSelect={select} /></div>}
        {Object.keys(sigCount).length > 0 && (
          <div className="chips" style={{ marginTop: 14 }}>
            {Object.entries(sigCount).sort((a, b) => b[1] - a[1]).map(([k, n]) => <span key={k} className="chip"><span className="code">{k}</span><span className="muted">{n}</span></span>)}
          </div>
        )}
      </Card>
      <div className="steps">
        {tl.map((e, i) => <Step key={i} e={e} i={i} selected={sel === i} onSelect={setSel} refEl={(el) => { refs.current[i] = el; }} />)}
        {!tl.length && <p className="ar-small muted">This run has no events yet.</p>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- page */
export default function RunExplorer({ live, refreshKey, runId, onPick }) {
  const [list] = useAsync(() => (live ? api.runs(50).then((d) => d.runs) : Promise.resolve([])), [live, refreshKey]);
  const [q, setQ] = React.useState("");
  const [only, setOnly] = React.useState("all");
  const runs = (list.data || [])
    .filter((r) => !q || `${r.run_id} ${r.profile}`.toLowerCase().includes(q.toLowerCase()))
    .filter((r) => only === "all" || (only === "flagged" ? worstOf(r.counts) !== "ALLOW" : r.killed))
    .sort((a, b) => SEV[worstOf(b.counts)] - SEV[worstOf(a.counts)] || (b.ira_max || 0) - (a.ira_max || 0));
  React.useEffect(() => { if (!runId && runs.length && live) onPick(runs[0].run_id); }, [runs.length, runId, live]); // eslint-disable-line
  return (
    <div className="runs-page">
      <aside className="runs-list">
        <div style={{ display: "flex", gap: 8, padding: "12px 12px 8px" }}>
          <Input placeholder="run id or profile" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
        </div>
        <div style={{ display: "flex", gap: 6, padding: "0 12px 10px" }}>
          {[["all", "All"], ["flagged", "Flagged"], ["killed", "Killed"]].map(([k, l]) => <Button key={k} size="sm" variant={only === k ? "ink" : "secondary"} onClick={() => setOnly(k)}>{l}</Button>)}
        </div>
        {list.error && !list.data && <div style={{ padding: 12 }}><ErrorNote error={list.error} /></div>}
        {!live && <p className="ar-caption muted" style={{ padding: 12 }}>Connect the service to list runs.</p>}
        {runs.map((r) => (
          <button key={r.run_id} className={`run-row ${r.run_id === runId ? "is-on" : ""}`} onClick={() => onPick(r.run_id)}>
            <span className="code run-id">{r.run_id}</span>
            <span className="ar-caption muted">{r.profile} · {r.actions} actions</span>
            <span className="run-meta"><Verdict v={worstOf(r.counts)} /><span className="ar-mono muted">max {fmt(r.ira_max)}</span></span>
          </button>
        ))}
        {live && list.data && !runs.length && <p className="ar-caption muted" style={{ padding: 12 }}>No runs in memory.</p>}
      </aside>
      <section className="runs-detail">
        {runId ? <RunDetail runId={runId} live={live} refreshKey={refreshKey} /> : <p className="ar-small muted" style={{ padding: 24 }}>Pick a run.</p>}
      </section>
    </div>
  );
}
