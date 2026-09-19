/* The Board: the one screen of the console. Input connectors (HappyRobot, OpenAI-compatible, webhook…)
   flow into the AngryRobot guard, and the guard flows into levers (continue, escalate, kill…). Traffic
   moves along the edges; clicking any node or edge opens a drawer with the detail (runs, alerts,
   escalations, connector config). The canvas pattern is lifted from PhoneFlow's builder
   (angryrobots/apps/app/src/components/flow): React Flow + custom nodes with Handles + a side panel. */
import React from "react";
import {
  Background, BaseEdge, Controls, EdgeLabelRenderer, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider,
  addEdge, applyEdgeChanges, applyNodeChanges, getBezierPath, useNodesInitialized, useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Badge, Button, Card, Dialog, Icon, Input, Select, Tabs, Verdict } from "../ds";
import { api } from "../api";
import { ErrorNote, Signals, useAsync } from "./shared";
import { CopyField, Escalations, StatusBadge, WorkflowDetail } from "./Platform";
import { Overview, Runs, TryAction, useData } from "./Console";
import RoundPanel from "./Round";

/* ---------------------------------------------------------------- catalog */
// One connector per provider. Only HappyRobot has an adapter today (providers.py); the rest are announced.
// Logos: frontend/public/providers/<id>.svg — a monogram is drawn when the file is missing.
export const INPUTS = {
  happyrobot: { label: "HappyRobot", source: "happyrobot", available: true },
  openai: { label: "OpenAI", source: "openai", available: false },
  claude: { label: "Claude", source: "claude", available: false },
  gemini: { label: "Gemini", source: "gemini", available: false },
  webhook: { label: "Webhook", source: "webhook", available: false, hidden: true },   // legacy workflows created by hand
};
const LOGO_BASE = `${import.meta.env.BASE_URL}providers/`;
function ProviderLogo({ id, size = 22 }) {
  const [broken, setBroken] = React.useState(false);
  const cat = INPUTS[id] || INPUTS.webhook;
  if (broken) return <span className="plogo plogo--mono" style={{ width: size, height: size, fontSize: size * 0.55 }}>{cat.label[0]}</span>;
  return <img className="plogo" src={`${LOGO_BASE}${id}.svg`} alt="" width={size} height={size} onError={() => setBroken(true)} />;
}
// Verdict → directive is fixed on the service (after_turn): ALLOW continue · WARN continue+note · DEFER escalate · KILL kill.
// Notify is the workflow's control_url: the service POSTs every non-continue directive and control change there.
export const OUTPUTS = {
  continue: { label: "Continue", icon: "check", verdicts: ["ALLOW"], tone: "paper" },
  warn: { label: "Supervisor note", icon: "eye", verdicts: ["WARN"], tone: "paper" },
  escalate: { label: "Escalate", icon: "hand", verdicts: ["DEFER"], tone: "sand" },
  kill: { label: "Kill", icon: "octagon", verdicts: ["KILL"], tone: "ink" },
  notify: { label: "Notify", icon: "siren", verdicts: ["DEFER", "KILL"], tone: "paper" },
  call: { label: "HappyRobot call", icon: "phone", verdicts: ["KILL"], tone: "freight" },   // rounds: the last trigger, on KILL
};
const VERDICTS = ["ALLOW", "WARN", "DEFER", "KILL"];
const STORE = "ar_board_v3";
const GUARD_ID = "guard";

/* ---------------------------------------------------------------- graph seed + persistence */
function seedGraph(workflows) {
  const inputs = workflows.slice(0, 6).map((w, i) => ({
    id: `in-${w.id}`, type: "connector", position: { x: 40, y: 60 + i * 150 },
    data: { kind: INPUTS[w.source] ? w.source : "webhook", label: w.name, profile: w.base_profile, mode: w.mode, workflow_id: w.id, status: w.status },
  }));
  const guard = { id: GUARD_ID, type: "guard", position: { x: 440, y: 60 + Math.max(0, inputs.length - 1) * 75 }, data: { profile: "default" }, deletable: false };
  const outs = ["continue", "escalate", "kill"].map((k, i) => ({ id: `out-${k}`, type: "lever", position: { x: 860, y: 40 + i * 150 }, data: { kind: k } }));
  const edges = [
    ...inputs.map((n) => ({ id: `e-${n.id}`, source: n.id, target: GUARD_ID, type: "traffic", data: { verdicts: [] } })),
    ...outs.map((n) => ({ id: `e-${n.id}`, source: GUARD_ID, target: n.id, type: "traffic", data: { verdicts: OUTPUTS[n.data.kind].verdicts } })),
  ];
  return { nodes: [...inputs, guard, ...outs], edges };
}
const loadGraph = () => {
  try {
    const g = JSON.parse(localStorage.getItem(STORE)); if (!g) return null;
    const nodes = g.nodes.filter((n) => n.type !== "lever" || OUTPUTS[n.data.kind]);
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes, edges: g.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
  } catch { return null; }
};
const saveGraph = (g) => { try { localStorage.setItem(STORE, JSON.stringify(g)); } catch { /* blocked storage */ } };

/* ---------------------------------------------------------------- traffic model
   One event per turn, split into what came UP into the guard and what went DOWN to the agent. */
function eventsFromRuns(runs) {
  const out = [];
  for (const r of runs) {
    for (const [i, e] of (r.timeline || []).entries()) {
      const base = { key: `${r.run_id}-${i}`, run_id: r.run_id, profile: r.profile, persona: r.persona, at: e.at };
      if (e.phase === "input") out.push({ ...base, dir: "up", kind: e.kind, text: e.content, signals: e.signals || [] });
      else if (e.action) {
        out.push({ ...base, dir: "up", kind: e.action.tool === "say" ? "utterance" : "tool_call", text: e.action.text || `${e.action.tool}(${JSON.stringify(e.action.args || {})})`,
                   reasoning: e.reasoning_excerpt, proposed: true });
        out.push({ ...base, key: `${base.key}-v`, dir: "down", kind: "verdict", verdict: e.verdict, ira: e.ira, lever: e.enforcement, explanation: e.explanation,
                   signals: e.signals || [], decided_by: e.decided_by });
      }
    }
  }
  return out;
}
const detailCache = new Map();   // run_id → { key: actions count, run }
// runIds: the Round tab passes the five runs of its round, so the strip, the edges and the guard's counters
// show only that round — never other agents that happen to be sending traffic to the service.
function useTraffic(live, refreshKey, runIds) {
  const key = runIds ? runIds.join(",") : "*";
  return useAsync(async () => {
    if (!live) return [];
    if (runIds) return (await Promise.all(runIds.map((id) => api.run(id).catch(() => null)))).filter(Boolean);
    const { runs } = await api.runs(8);
    return Promise.all(runs.slice(0, 8).map(async (r) => {
      const hit = detailCache.get(r.run_id);
      if (hit && hit.key === r.actions) return hit.run;
      try { const run = await api.run(r.run_id); detailCache.set(r.run_id, { key: r.actions, run }); return run; }
      catch { return { ...r, timeline: [] }; }
    }));
  }, [live, refreshKey, key]);
}

/* ---------------------------------------------------------------- nodes */
const HANDLE = { width: 10, height: 10, borderRadius: 0, background: "var(--ar-paper)", border: "1.5px solid var(--ar-black)" };

function Shell({ selected, tone = "paper", children, badge, extra = "" }) {
  return (
    <div className={`bn bn--${tone} ${selected ? "is-selected" : ""} ${extra}`}>
      {badge}
      {children}
    </div>
  );
}
function InputNode({ data, selected }) {
  const cat = INPUTS[data.kind] || INPUTS.webhook;
  const seat = data.seat;   // this connector is a seat of the running round (Round tab)
  return (
    <Shell selected={selected} extra={seat ? `is-seat is-seat-${seat.status}${seat.malicious ? " is-malicious" : ""}` : ""}>
      <div className="bn-head"><ProviderLogo id={data.kind} size={18} /><span className="ar-mono muted">{cat.label.toUpperCase()}{data.external_slug ? ` · ${data.external_slug}` : ""}</span></div>
      <strong className="bn-title">{data.label || cat.label}</strong>
      {seat && (
        <div className="bn-seat">
          <span><b>{seat.agent}</b> · {seat.status === "active" ? "on the call" : seat.status}</span>
          {seat.worst ? <Verdict v={seat.worst} /> : null}
          {seat.malicious ? <span className="chip chip--malicious">{seat.malicious}</span> : null}
        </div>
      )}
      {data.workflow_id && <span className="bn-sub">policy {data.profile} · {data.mode}</span>}
      <div className="bn-foot">
        {data.workflow_id ? <StatusBadge status={data.status || "live"} /> : <Badge tone="sand">Not registered</Badge>}
        {data.count ? <span className="ar-mono muted">{data.count} turns ↑</span> : null}
      </div>
      <Handle type="source" position={Position.Right} style={HANDLE} />
    </Shell>
  );
}
function GuardNode({ data, selected }) {
  return (
    <Shell selected={selected} tone="freight">
      <Handle type="target" position={Position.Left} style={HANDLE} />
      <div className="bn-head"><Icon name="brain" size={16} /><span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>ANGRYROBOT</span></div>
      <strong className="bn-title">IRA audit</strong>
      {data.judge && <span className="bn-sub" style={{ color: "var(--text-on-dark-muted)" }}>judge {data.judge}{data.agent ? ` · agent ${data.agent}` : ""}{data.commit ? ` · ${data.commit}` : ""}</span>}
      <div className="bn-bands">
        {VERDICTS.map((v) => <span key={v} className={`bn-band ${v}`}>{v} <b>{data.counts?.[v] || 0}</b></span>)}
      </div>
      <Handle type="source" position={Position.Right} style={HANDLE} />
    </Shell>
  );
}
function OutputNode({ data, selected }) {
  const cat = OUTPUTS[data.kind] || OUTPUTS.continue;
  return (
    <Shell selected={selected} tone={cat.tone}>
      <Handle type="target" position={Position.Left} style={HANDLE} />
      <div className="bn-head"><Icon name={cat.icon} size={16} /><span className="ar-mono" style={{ opacity: .7 }}>LEVER</span></div>
      <strong className="bn-title">{cat.label}</strong>
      {data.call && <span className="bn-sub" style={{ opacity: .9 }}>{data.call}</span>}
      {data.count != null && <div className="bn-foot"><span className="ar-mono" style={{ opacity: .8 }}>{data.count} ↓</span>{data.waiting ? <Badge tone="accent" dot>{data.waiting} waiting</Badge> : null}</div>}
    </Shell>
  );
}
const NODE_TYPES = { connector: InputNode, guard: GuardNode, lever: OutputNode };

/* ---------------------------------------------------------------- edges: a labelled pipe with a live count */
function TrafficEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }) {
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const n = data?.count || 0;
  const label = data?.verdicts?.length ? data.verdicts.join(" · ") : "per turn";
  return (
    <>
      <BaseEdge id={id} path={path} style={{ stroke: selected ? "var(--ar-black)" : "var(--ar-grey-400)", strokeWidth: selected ? 2 : 1.4, strokeDasharray: n ? undefined : "4 4" }} />
      {n > 0 && <circle r="3" fill="var(--ar-green)"><animateMotion dur={`${Math.max(1.2, 4 - Math.log10(n + 1))}s`} repeatCount="indefinite" path={path} /></circle>}
      <EdgeLabelRenderer>
        <div className={`be-label ${selected ? "is-selected" : ""}`} style={{ transform: `translate(-50%,-50%) translate(${lx}px,${ly}px)` }}>
          <span>{label}</span>{n ? <b>{n}</b> : null}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
const EDGE_TYPES = { traffic: TrafficEdge };

/* ---------------------------------------------------------------- palette (drag source) */
function Palette({ hasGuard, providers, onProvider }) {
  const drag = (payload) => (e) => { e.dataTransfer.setData("application/angryrobot-node", JSON.stringify(payload)); e.dataTransfer.effectAllowed = "move"; };
  const Item = ({ icon, label, payload, disabled }) => (
    <div className={`pal-item ${disabled ? "is-off" : ""}`} draggable={!disabled} onDragStart={drag(payload)} title={disabled ? "Already on the board" : "Drag onto the board"}>
      <Icon name={icon} size={16} />
      <div className="pal-label">{label}</div>
    </div>
  );
  const status = Object.fromEntries((providers || []).map((p) => [p.id, p]));
  return (
    <aside className="palette" aria-label="Connectors">
      <span className="ar-overline muted">Providers</span>
      {Object.entries(INPUTS).filter(([, c]) => !c.hidden).map(([k, c]) => {
        const live = c.available && status[k]?.configured !== false;
        return (
          <button key={k} className={`prov-tile ${c.available ? "" : "is-soon"}`} disabled={!c.available} draggable={live} onDragStart={drag({ type: "provider", kind: k })}
                  onClick={() => c.available && onProvider(k)} title={!c.available ? "Coming soon" : status[k]?.configured === false ? "Add HAPPYROBOT_API_KEY on the service" : "Connect existing agents"}>
            <ProviderLogo id={k} size={26} />
            <span className="prov-name">{c.label}</span>
            {!c.available ? <span className="prov-tag">Soon</span>
              : status[k]?.configured === false ? <span className="prov-tag prov-tag--warn">No key</span>
              : status[k]?.linked ? <span className="prov-tag prov-tag--ok">{status[k].linked}</span> : null}
          </button>
        );
      })}
      <span className="ar-overline muted" style={{ marginTop: 18 }}>Guard</span>
      <Item icon="brain" label="AngryRobot" payload={{ type: "guard" }} disabled={hasGuard} />
      <span className="ar-overline muted" style={{ marginTop: 18 }}>Levers</span>
      {Object.entries(OUTPUTS).map(([k, c]) => <Item key={k} icon={c.icon} label={c.label} payload={{ type: "lever", kind: k }} />)}
    </aside>
  );
}

/* ---------------------------------------------------------------- traffic strip */
function TrafficStrip({ events, filter, filterLabel, onClear, onDisconnect, onOpenRun, loading }) {
  const rows = events.filter((e) => !filter || filter(e)).slice(-80).reverse();
  return (
    <section className="traffic" aria-label="Traffic">
      <header className="traffic-head">
        <span className="ar-overline muted">Traffic · {rows.length}</span>
        <span className="ar-caption muted"><b style={{ color: "var(--ar-green)" }}>↑</b> in · <b>↓</b> out{filterLabel ? ` · ${filterLabel}` : ""}</span>
        {onDisconnect && <Button size="sm" variant="secondary" onClick={onDisconnect} iconLeft={<Icon name="x" size={14} />}>Disconnect</Button>}
        {filter && <Button size="sm" variant="secondary" onClick={onClear}>All traffic</Button>}
      </header>
      <div className="traffic-body">
        {loading && <p className="ar-caption muted" style={{ padding: 12 }}>Loading runs…</p>}
        {rows.map((e) => (
          <button key={e.key} className={`tr-row tr-${e.dir}`} onClick={() => onOpenRun(e.run_id)} title="Open the run">
            <span className={`tr-dir ${e.dir}`}>{e.dir === "up" ? "↑" : "↓"}</span>
            <span className="ar-mono muted tr-run">{e.persona || e.profile}</span>
            {e.dir === "up" ? (
              <span className="tr-text"><span className="ar-mono muted">{e.kind}</span> {e.text}{e.reasoning ? <span className="muted"> · reasoning: “{e.reasoning.slice(0, 80)}…”</span> : null}</span>
            ) : (
              <span className="tr-text"><Verdict v={e.verdict} /> <span className="ar-mono">IRA {(e.ira ?? 0).toFixed(1)}</span>{e.lever && e.lever !== "ninguna" ? <span className="muted"> · lever: {e.lever}</span> : null}
                {e.signals?.length ? <Signals list={e.signals.slice(0, 3)} /> : null}</span>
            )}
          </button>
        ))}
        {!loading && !rows.length && <p className="ar-caption muted" style={{ padding: 12 }}>No traffic.</p>}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- drawers (the "pop-ups") */
function Drawer({ title, eyebrow, onClose, children, wide }) {
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside className="drawer" style={wide ? { width: "min(760px,100vw)" } : undefined} aria-label={title}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, padding: "24px 24px 18px", borderBottom: "1px solid var(--border-subtle)" }}>
        <div><span className="ar-mono muted">{eyebrow}</span><h3 className="ar-h5" style={{ marginTop: 8 }}>{title}</h3></div>
        <button onClick={onClose} aria-label="Close" className="ar-x">×</button>
      </div>
      <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20, overflow: "auto", flex: 1 }}>{children}</div>
    </aside>
  );
}

function InputDrawer({ node, live, profiles, onChange, onRemove, onClose, refreshKey }) {
  const d = node.data; const cat = INPUTS[d.kind];
  const [form, setForm] = React.useState({ label: d.label || cat.label, profile: d.profile || "default", mode: d.mode || "enforce" });
  const [busy, setBusy] = React.useState(false); const [err, setErr] = React.useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const register = async () => {
    setBusy(true); setErr(null);
    try {
      const wf = await api.createWorkflow({ name: form.label, source: cat.source, base_profile: form.profile, mode: form.mode, goal: "", constraints: [], control_url: null });
      onChange({ ...d, ...form, workflow_id: wf.id, status: wf.status || "live" });
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Drawer eyebrow={`INPUT · ${cat.label.toUpperCase()}`} title={d.label || cat.label} onClose={onClose} wide={Boolean(d.workflow_id)}>
      {d.workflow_id ? (
        <WorkflowDetail id={d.workflow_id} live={live} refreshKey={refreshKey} onChanged={() => {}} />
      ) : (
        <Card padding={24} eyebrow="REGISTER">
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Input label="Name" value={form.label} onChange={set("label")} />
            <div className="form-2">
              <Select label="Policy profile" value={form.profile} onChange={set("profile")} options={profiles.map((p) => ({ value: p, label: p }))} />
              <Select label="Mode" value={form.mode} onChange={set("mode")} options={[{ value: "enforce", label: "Enforce" }, { value: "observe", label: "Observe only" }]} />
            </div>
            {err && <ErrorNote error={err} />}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <Button onClick={live ? register : () => onChange({ ...d, ...form })} disabled={busy}>{live ? (busy ? "Registering…" : "Register") : "Save"}</Button>
              {!live && <Button variant="secondary" onClick={() => { window.location.hash = "#/console/settings"; }}>Connect the service</Button>}
            </div>
          </div>
        </Card>
      )}
      <Button variant="secondary" size="sm" onClick={onRemove} style={{ alignSelf: "flex-start" }} iconLeft={<Icon name="x" size={15} />}>Remove</Button>
    </Drawer>
  );
}

function GuardDrawer({ data, live, onOpenRun, onClose, initialTab = "alerts" }) {
  const [tab, setTab] = React.useState(initialTab);
  return (
    <Drawer eyebrow="ANGRYROBOT" title="IRA audit" onClose={onClose} wide>
      <Tabs value={tab} onChange={setTab} items={[{ value: "alerts", label: "Alerts" }, { value: "runs", label: "Runs" }, { value: "try", label: "Audit an action" }]} />
      {tab === "alerts" && <Overview data={data} live={live} onOpenRun={onOpenRun} />}
      {tab === "runs" && <Runs data={data} onOpenRun={onOpenRun} />}
      {tab === "try" && <TryAction live={live} onConnect={() => { window.location.hash = "#/console/settings"; }} />}
    </Drawer>
  );
}

function OutputDrawer({ node, live, refreshKey, onRemove, onClose, data, onOpenRun, connectors }) {
  const d = node.data; const cat = OUTPUTS[d.kind];
  return (
    <Drawer eyebrow="LEVER" title={cat.label} onClose={onClose} wide={d.kind !== "notify"}>
      {d.kind === "escalate" && <Escalations live={live} refreshKey={refreshKey} onChanged={() => {}} />}
      {d.kind === "kill" && <Overview data={data} live={live} onOpenRun={onOpenRun} />}
      {d.kind === "notify" && <NotifyConfig live={live} connectors={connectors} refreshKey={refreshKey} />}
      <Button variant="secondary" size="sm" onClick={onRemove} style={{ alignSelf: "flex-start" }} iconLeft={<Icon name="x" size={15} />}>Remove</Button>
    </Drawer>
  );
}

/* Notify = control_url on each registered workflow: the service POSTs directives and control changes there. */
function NotifyConfig({ live, connectors, refreshKey }) {
  const ids = connectors.map((n) => n.data.workflow_id).filter(Boolean);
  const [wfs, reload] = useAsync(() => (live ? Promise.all(ids.map((id) => api.workflow(id).catch(() => null))) : Promise.resolve([])), [live, ids.join(","), refreshKey]);
  const current = (wfs.data || []).filter(Boolean);
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false); const [err, setErr] = React.useState(null); const [ok, setOk] = React.useState(0);
  React.useEffect(() => { const first = current.find((w) => w.control_url); if (first && !url) setUrl(first.control_url); }, [current.length]); // eslint-disable-line
  const apply = async (value) => {
    setBusy(true); setErr(null);
    try { await Promise.all(ids.map((id) => api.updateWorkflow(id, { control_url: value || null }))); setOk((n) => n + 1); reload(); }
    catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Card padding={24} eyebrow="CONTROL URL">
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Input label="Webhook" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
        {err && <ErrorNote error={err} />}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Button size="sm" onClick={() => apply(url.trim())} disabled={!live || busy || !ids.length}>{busy ? "Saving…" : `Apply to ${ids.length} workflow${ids.length === 1 ? "" : "s"}`}</Button>
          <Button size="sm" variant="secondary" onClick={() => { setUrl(""); apply(""); }} disabled={!live || busy || !ids.length}>Clear</Button>
          {!live && <Button size="sm" variant="secondary" onClick={() => { window.location.hash = "#/console/settings"; }}>Connect the service</Button>}
        </div>
        {current.length > 0 && (
          <table className="table"><tbody>
            {current.map((w) => <tr key={w.id} style={{ cursor: "default" }}><td>{w.name}</td><td className="code" style={{ color: w.control_url ? "var(--text-body)" : "var(--text-muted)" }}>{w.control_url || "—"}</td></tr>)}
          </tbody></table>
        )}
        {ok > 0 && <span className="ar-caption" style={{ color: "var(--status-positive)" }}>Saved.</span>}
      </div>
    </Card>
  );
}

/* ---------------------------------------------------------------- HappyRobot: pick existing agents in the org and attach the guard
   GET /v1/providers/happyrobot/workflows lists the org (with the AngryRobot workflow each one is already linked to);
   POST /v1/providers/happyrobot/connect registers the chosen ones, creates the Custom LLM credential in the org
   and returns the one manual step left in the builder. "Sync" = connect everything not linked yet. */
function HappyRobotDialog({ open, onClose, live, profiles, onConnected }) {
  const [list, reload] = useAsync(() => (open && live ? api.hrWorkflows().then((d) => d.workflows) : Promise.resolve(null)), [open, live]);
  const [picked, setPicked] = React.useState({});
  const [profile, setProfile] = React.useState(profiles[0] || "default");
  const [mode, setMode] = React.useState("enforce");
  const [busy, setBusy] = React.useState(false); const [err, setErr] = React.useState(null); const [done, setDone] = React.useState(null);
  React.useEffect(() => { if (open) { setPicked({}); setErr(null); setDone(null); } }, [open]);
  const rows = list.data || [];
  const unlinked = rows.filter((w) => !w.linked_workflow);
  const chosen = unlinked.filter((w) => picked[w.id]);
  const run = async (body) => {
    setBusy(true); setErr(null);
    try { const r = await api.hrConnect({ base_profile: profile, mode, ...body }); setDone(r); onConnected(r.results.filter((x) => x.workflow).map((x) => ({ ...x.workflow, external_slug: x.external_slug }))); reload(); }
    catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={onClose} eyebrow="HAPPYROBOT" title={done ? "Connected" : "Agents in the org"} width={760}
      footer={done ? <Button onClick={onClose}>Close</Button> : <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="secondary" disabled={busy || !unlinked.length} onClick={() => run({ all_unlinked: true })}>{busy ? "Working…" : `Sync all (${unlinked.length})`}</Button>
        <Button disabled={busy || !chosen.length} onClick={() => run({ workflow_ids: chosen.map((w) => w.id) })}>{busy ? "Working…" : `Connect ${chosen.length || ""}`}</Button>
      </>}>
      {!live && <p className="ar-small muted">Connect the service first (Settings).</p>}
      {err && <ErrorNote error={err} />}
      {list.error && !list.data && <ErrorNote error={list.error} onRetry={reload} />}
      {!done && list.data && (
        <>
          <div className="form-2">
            <Select label="Policy profile" value={profile} onChange={(e) => setProfile(e.target.value)} options={profiles.map((p) => ({ value: p, label: p }))} />
            <Select label="Mode" value={mode} onChange={(e) => setMode(e.target.value)} options={[{ value: "enforce", label: "Enforce" }, { value: "observe", label: "Observe only" }]} />
          </div>
          <table className="table" style={{ marginTop: 8 }}>
            <thead><tr><th style={{ width: 28 }}><input type="checkbox" checked={unlinked.length > 0 && chosen.length === unlinked.length}
              onChange={(e) => setPicked(Object.fromEntries(unlinked.map((w) => [w.id, e.target.checked])))} aria-label="Select all" /></th>
              <th>Agent</th><th>Version</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((w) => (
                <tr key={w.id} style={{ cursor: w.linked_workflow ? "default" : "pointer" }} onClick={() => !w.linked_workflow && setPicked((p) => ({ ...p, [w.id]: !p[w.id] }))}>
                  <td>{w.linked_workflow ? <Icon name="check" size={16} /> : <input type="checkbox" checked={!!picked[w.id]} readOnly aria-label={w.name} />}</td>
                  <td><div style={{ fontWeight: 500, color: "var(--text-strong)" }}>{w.name}</div><div className="ar-caption muted code">{w.slug}</div></td>
                  <td className="ar-mono">{w.version != null ? `v${w.version}` : "—"}{w.is_live ? " · live" : ""}</td>
                  <td>{w.linked_workflow ? <Badge tone="positive" dot>{w.linked_workflow}</Badge> : <Badge>not monitored</Badge>}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={4} className="muted">No workflows in the org.</td></tr>}
            </tbody>
          </table>
        </>
      )}
      {done && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {done.results.map((r) => (
            <Card key={r.external_id} padding={18} eyebrow={r.external_name || r.external_id}>
              {r.error && <p className="ar-small">{r.error}</p>}
              {r.workflow && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <Badge tone="positive" dot>{r.workflow.id}</Badge>
                    {r.already && <Badge>already linked</Badge>}
                    {r.credential?.id && <Badge tone="info">credential created</Badge>}
                    {r.credential?.error && <Badge tone="negative">credential failed</Badge>}
                  </div>
                  {r.credential?.error && <p className="ar-caption">{r.credential.error}</p>}
                  {r.credential && <CopyField label="CUSTOM LLM CREDENTIAL" value={r.credential.title} />}
                  {r.credential && <CopyField label="ENDPOINT" value={r.credential.endpoint} />}
                  {r.workflow.token && <CopyField label="WORKFLOW TOKEN (BEARER)" value={r.workflow.token} secret />}
                  {r.next_steps && <ol className="ar-small" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>{r.next_steps.map((t, i) => <li key={i}>{t}</li>)}</ol>}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </Dialog>
  );
}

/* ---------------------------------------------------------------- the round's own board
   Round tab: the five seats of the round in order -> AngryRobot -> the levers, including the HappyRobot
   call (the last trigger, on KILL). Kept apart from the Build board, which is stored and auto-places every
   workflow of the service, so neither view clutters the other. */
function roundLayout(seats) {
  const inputs = seats.map((x, i) => ({ id: `in-${x.workflow_id}`, type: "connector", position: { x: 0, y: i * 175 },
    data: { kind: INPUTS[x.source] ? x.source : "webhook", label: x.role, profile: "desk", mode: "enforce", workflow_id: x.workflow_id, status: "live" } }));
  const guard = { id: GUARD_ID, type: "guard", position: { x: 420, y: 330 }, data: { profile: "desk" }, deletable: false };
  const outs = ["continue", "warn", "escalate", "kill", "call"].map((k, i) => ({ id: `out-${k}`, type: "lever", position: { x: 840, y: i * 165 }, data: { kind: k } }));
  return { nodes: [...inputs, guard, ...outs],
           edges: [...inputs.map((n) => ({ id: `e-${n.id}`, source: n.id, target: GUARD_ID, type: "traffic", data: { verdicts: [] } })),
                   ...outs.map((n) => ({ id: `e-${n.id}`, source: GUARD_ID, target: n.id, type: "traffic", data: { verdicts: OUTPUTS[n.data.kind].verdicts } }))] };
}

/* ---------------------------------------------------------------- the board */
function BoardInner({ live, refreshKey, initial }) {
  const flow = useReactFlow();
  const [wfs] = useAsync(() => (live ? api.workflows() : Promise.resolve({ workflows: [], base_profiles: ["default"] })), [live, refreshKey]);
  const [health] = useAsync(() => api.health().catch(() => null), [live]);
  const data = useData(live, refreshKey);
  const [buildGraph, setBuildGraph] = React.useState(() => loadGraph());
  const [roundGraph, setRoundGraph] = React.useState(() => roundLayout([]));   // no round yet: just the guard and the levers
  const [leftTab, setLeftTab] = React.useState(() => { try { return localStorage.getItem("ar_left_tab") || "round"; } catch { return "round"; } });
  React.useEffect(() => { try { localStorage.setItem("ar_left_tab", leftTab); } catch { /* blocked */ } }, [leftTab]);
  const [round, setRound] = React.useState(null);
  const inRound = leftTab === "round";
  const graph = inRound ? roundGraph : buildGraph;
  const setGraph = inRound ? setRoundGraph : setBuildGraph;
  const [traffic] = useTraffic(live, refreshKey, inRound ? (round?.seats || []).map((x) => x.run_id) : null);
  React.useEffect(() => {
    if (round?.seats) setRoundGraph((g) => (g && g.roundId === round.id ? g : { ...roundLayout(round.seats), roundId: round.id }));
  }, [round?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => { const t = setTimeout(() => flow.fitView({ padding: 0.15, duration: 250 }), 80); return () => clearTimeout(t); }, [inRound, round?.id, flow]);
  const graphReady = Boolean(graph);
  const ready = useNodesInitialized();
  const canvasRef = React.useRef(null);
  // Fit once the nodes have been measured, and again whenever the canvas changes size (drawer, resize).
  const fitted = React.useRef(false);
  React.useEffect(() => { if (ready && !fitted.current) { fitted.current = true; flow.fitView({ padding: 0.2 }); } }, [ready, flow]);
  React.useEffect(() => {
    const el = canvasRef.current; if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => { if (fitted.current) flow.fitView({ padding: 0.2, duration: 200 }); });
    ro.observe(el); return () => ro.disconnect();
  }, [flow, graphReady]);
  const [sel, setSel] = React.useState(initial || null);          // {type:'node'|'edge', id, tab?}
  const [busyAll, setBusyAll] = React.useState(false); const [allErr, setAllErr] = React.useState(null);
  const [provider, setProvider] = React.useState(null);           // which provider dialog is open
  const [provs] = useAsync(() => (live ? api.providers().then((d) => d.providers) : Promise.resolve([])), [live, refreshKey]);
  // Put registered workflows on the board as connector nodes (skips the ones already there) and wire them to the guard.
  const placeWorkflows = (list) => patch((g) => {
    const have = new Set(g.nodes.filter((n) => n.type === "connector").map((n) => n.data.workflow_id));
    const fresh = list.filter((w) => w && !have.has(w.id));
    if (!fresh.length) return {};
    const y0 = Math.max(0, ...g.nodes.filter((n) => n.type === "connector").map((n) => n.position.y + 150));
    const nodes = fresh.map((w, i) => ({ id: `in-${w.id}`, type: "connector", position: { x: 40, y: y0 + i * 150 },
      data: { kind: INPUTS[w.source] ? w.source : "webhook", label: w.name, profile: w.base_profile, mode: w.mode, workflow_id: w.id, status: w.status, external_slug: w.external_slug } }));
    const edges = g.nodes.some((n) => n.id === GUARD_ID) ? nodes.map((n) => ({ id: `e-${n.id}`, source: n.id, target: GUARD_ID, type: "traffic", data: { verdicts: [] } })) : [];
    return { nodes: [...g.nodes, ...nodes], edges: [...g.edges, ...edges] };
  });
  // Workflows that exist on the service but not on the board (created elsewhere, or after a sync) get placed automatically.
  React.useEffect(() => { if (!inRound && graph && wfs.data?.workflows?.length) placeWorkflows(wfs.data.workflows); }, [graph ? 1 : 0, wfs.data, inRound]); // eslint-disable-line
  const controlAll = async (action) => { setBusyAll(true); setAllErr(null); try { await api.controlAll(action); } catch (x) { setAllErr(x); } finally { setBusyAll(false); } };

  // First visit: seed the board from the connected workflows.
  React.useEffect(() => { if (!buildGraph && wfs.data) setBuildGraph(seedGraph(wfs.data.workflows || [])); }, [buildGraph, wfs.data]);
  React.useEffect(() => { if (buildGraph) saveGraph(buildGraph); }, [buildGraph]);

  const events = React.useMemo(() => eventsFromRuns(traffic.data || []), [traffic.data]);
  const profiles = wfs.data?.base_profiles || ["default"];
  const wfById = Object.fromEntries((wfs.data?.workflows || []).map((w) => [w.id, w]));
  const escOpen = (wfs.data?.workflows || []).reduce((n, w) => n + (w.stats?.open_escalations || 0), 0);

  // Decorate nodes/edges with live counts (never persisted).
  const nodes = React.useMemo(() => (graph?.nodes || []).map((n) => {
    if (n.type === "connector") {
      const w = wfById[n.data.workflow_id];
      const count = events.filter((e) => e.dir === "up" && e.kind === "user_turn" && (e.profile === n.data.profile || e.profile === n.data.workflow_id)).length;
      const seat = round?.seats?.find((x) => x.workflow_id === n.data.workflow_id);
      const seatData = seat ? { agent: seat.agent, status: seat.status, worst: seat.worst,
                                malicious: seat.malicious && seat.malicious !== "hidden" ? seat.malicious.label : null } : null;
      return { ...n, data: { ...n.data, status: w?.status || n.data.status, count, seat: seatData } };
    }
    if (n.type === "guard") {
      const counts = {}; events.filter((e) => e.dir === "down").forEach((e) => { counts[e.verdict] = (counts[e.verdict] || 0) + 1; });
      return { ...n, deletable: false, data: { ...n.data, counts, judge: health.data?.judge?.model?.split("/").pop(), agent: health.data?.agent_default_model?.split("/").pop(), commit: health.data?.commit } };
    }
    const verdicts = (graph.edges.find((e) => e.target === n.id)?.data?.verdicts) || [];
    const count = events.filter((e) => e.dir === "down" && verdicts.includes(e.verdict)).length;
    const callEv = n.data.kind === "call" ? [...(round?.events || [])].reverse().find((e) => e.kind === "call") : null;
    return { ...n, data: { ...n.data, count, waiting: n.data.kind === "escalate" ? escOpen : 0,
                           call: n.data.kind === "call" ? (callEv ? `${callEv.status} · ${callEv.call?.phone || ""}` : "waits for a KILL") : undefined } };
  }), [graph, events, wfById, health.data, escOpen, round]);
  const edges = React.useMemo(() => (graph?.edges || []).map((e) => {
    const src = graph.nodes.find((n) => n.id === e.source);
    const count = src?.type === "guard"
      ? events.filter((x) => x.dir === "down" && (e.data?.verdicts || []).includes(x.verdict)).length
      : events.filter((x) => x.dir === "up" && (x.profile === src?.data?.profile || x.profile === src?.data?.workflow_id)).length;
    return { ...e, type: "traffic", data: { ...e.data, count } };
  }), [graph, events]);

  const patch = (fn) => setGraph((g) => ({ ...g, ...fn(g) }));
  const onNodesChange = (ch) => patch((g) => ({ nodes: applyNodeChanges(ch.filter((c) => !(c.type === "remove" && c.id === GUARD_ID)), g.nodes) }));
  const onEdgesChange = (ch) => patch((g) => ({ edges: applyEdgeChanges(ch, g.edges) }));
  const isValid = (c) => {
    const s = graph.nodes.find((n) => n.id === c.source), t = graph.nodes.find((n) => n.id === c.target);
    return (s?.type === "connector" && t?.type === "guard") || (s?.type === "guard" && t?.type === "lever");
  };
  const onConnect = (c) => patch((g) => {
    const t = g.nodes.find((n) => n.id === c.target);
    const verdicts = t?.type === "lever" ? OUTPUTS[t.data.kind].verdicts : [];
    return { edges: addEdge({ ...c, id: `e-${c.source}-${c.target}`, type: "traffic", data: { verdicts } }, g.edges) };
  });
  const onDrop = (e) => {
    e.preventDefault();
    const raw = e.dataTransfer.getData("application/angryrobot-node"); if (!raw) return;
    const p = JSON.parse(raw);
    if (p.type === "provider") { setProvider(p.kind); return; }
    if (p.type === "guard" && graph.nodes.some((n) => n.type === "guard")) return;
    const position = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const id = p.type === "guard" ? GUARD_ID : `${p.type}-${p.kind}-${Date.now().toString(36)}`;
    const data = p.type === "connector" ? { kind: p.kind, label: INPUTS[p.kind].label, profile: "default", mode: "enforce" } : p.type === "lever" ? { kind: p.kind } : { profile: "default" };
    patch((g) => ({ nodes: [...g.nodes, { id, type: p.type, position, data }] }));
    setSel({ type: "node", id });
  };
  const setNodeData = (id, d) => patch((g) => ({ nodes: g.nodes.map((n) => (n.id === id ? { ...n, data: d } : n)) }));
  const removeNode = (id) => { patch((g) => ({ nodes: g.nodes.filter((n) => n.id !== id), edges: g.edges.filter((e) => e.source !== id && e.target !== id) })); setSel(null); };
  const removeEdge = (id) => { patch((g) => ({ edges: g.edges.filter((e) => e.id !== id) })); setSel(null); };

  // Traffic filter follows the selection.
  const filter = React.useMemo(() => {
    if (!sel) return null;
    if (sel.type === "edge") {
      const e = graph?.edges.find((x) => x.id === sel.id); const s = graph?.nodes.find((n) => n.id === e?.source);
      if (!e) return null;
      return s?.type === "guard" ? (x) => x.dir === "down" && (e.data?.verdicts || []).includes(x.verdict)
                                 : (x) => x.dir === "up" && (x.profile === s?.data?.profile || x.profile === s?.data?.workflow_id);
    }
    const n = graph?.nodes.find((x) => x.id === sel.id);
    if (n?.type === "connector") return (x) => x.profile === n.data.profile || x.profile === n.data.workflow_id;
    if (n?.type === "lever") { const v = OUTPUTS[n.data.kind].verdicts; return (x) => x.dir === "down" && v.includes(x.verdict); }
    return null;
  }, [sel, graph]);

  const filterLabel = (() => {
    if (!sel) return "";
    if (sel.type === "edge") { const e = graph?.edges.find((x) => x.id === sel.id); const s0 = graph?.nodes.find((n) => n.id === e?.source); const t0 = graph?.nodes.find((n) => n.id === e?.target);
      return s0?.type === "guard" ? `guard → ${OUTPUTS[t0?.data?.kind]?.label || ""}` : `${s0?.data?.label || ""} → guard`; }
    const n = graph?.nodes.find((x) => x.id === sel.id);
    return n?.type === "lever" ? OUTPUTS[n.data.kind]?.label : n?.type === "connector" ? n.data.label : "";
  })();
  const openById = (id) => { window.location.hash = `#/console/runs/${encodeURIComponent(id)}`; };
  const selNode = sel?.type === "node" ? nodes.find((n) => n.id === sel.id) : null;
  const selEdge = sel?.type === "edge" ? graph?.edges.find((e) => e.id === sel.id) : null;
  const issues = [];
  if (inRound && !round) issues.push("No round yet: press Randomize agents on the left.");
  else if (graph && !inRound) {
    if (!graph.nodes.some((n) => n.type === "guard")) issues.push("No guard on the board.");
    graph.nodes.filter((n) => n.type === "connector" && !graph.edges.some((e) => e.source === n.id)).forEach((n) => issues.push(`${n.data.label} → guard missing.`));
    graph.nodes.filter((n) => n.type === "connector" && !n.data.workflow_id).forEach((n) => issues.push(`${n.data.label} not registered.`));
    if (!graph.edges.some((e) => (e.data?.verdicts || []).includes("KILL"))) issues.push("No Kill lever.");
    if (!graph.edges.some((e) => (e.data?.verdicts || []).includes("DEFER"))) issues.push("No Escalate lever.");
  }

  if (!graph) return <p className="ar-small muted" style={{ padding: 24 }}>Laying out the board…</p>;
  return (
    <div className={`board ${leftTab === "round" ? "is-round" : ""}`}>
      <div className="board-left">
        <div className="left-tabs" role="tablist">
          <button role="tab" aria-selected={leftTab === "round"} className={leftTab === "round" ? "is-on" : ""} onClick={() => setLeftTab("round")}>Round</button>
          <button role="tab" aria-selected={leftTab === "build"} className={leftTab === "build" ? "is-on" : ""} onClick={() => setLeftTab("build")}>Build</button>
        </div>
        {leftTab === "round" ? <RoundPanel live={live} onRound={setRound} />
          : <Palette hasGuard={graph.nodes.some((n) => n.type === "guard")} providers={provs.data} onProvider={setProvider} />}
      </div>
      <div className="board-main">
        <div className="board-canvas" ref={canvasRef} onDrop={onDrop} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} isValidConnection={isValid}
            onNodeClick={(_, n) => setSel({ type: "node", id: n.id })} onEdgeClick={(_, e) => setSel({ type: "edge", id: e.id })} onPaneClick={() => setSel(null)}
            fitView fitViewOptions={{ padding: 0.2 }} selectNodesOnDrag={false} proOptions={{ hideAttribution: true }} deleteKeyCode={["Backspace", "Delete"]}>
            <Background gap={18} size={1} color="var(--ar-grey-300)" />
            <MiniMap pannable zoomable style={{ width: 140, height: 90 }} nodeColor={(n) => (n.type === "guard" ? "#2E5B46" : n.type === "lever" ? "#D9C7A9" : "#ffffff")} />
            <Controls showInteractive={false} />
          </ReactFlow>
          {issues.length > 0 && (
            <div className="board-issues" role="status">
              <Icon name="alert-triangle" size={16} />
              <span>{issues.join(" · ")}</span>
            </div>
          )}
          <div className="board-legend">
            {live ? (
              <>
                <Button size="sm" onClick={() => setProvider("happyrobot")} iconLeft={<ProviderLogo id="happyrobot" size={14} />}>Sync HappyRobot</Button>
                <Button size="sm" variant="secondary" disabled={busyAll} onClick={() => controlAll("pause")}>Pause all</Button>
                <Button size="sm" variant="secondary" disabled={busyAll} onClick={() => controlAll("resume")}>Resume all</Button>
                <Button size="sm" variant="secondary" disabled={busyAll} onClick={() => { if (window.confirm("Kill every live run of every workflow?")) controlAll("kill"); }} iconLeft={<Icon name="octagon" size={14} />}>Kill all</Button>
              </>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => { window.location.hash = "#/console/settings"; }} iconLeft={<Icon name="plug" size={14} />}>Connect the service</Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => { if (inRound) { setRoundGraph(round ? { ...roundLayout(round.seats), roundId: round.id } : roundLayout([])); return; } localStorage.removeItem(STORE); setBuildGraph(seedGraph(wfs.data?.workflows || [])); }}>Reset layout</Button>
          </div>
          {allErr && <div className="board-issues" style={{ top: 64 }}><Icon name="alert-triangle" size={16} /><span>{String(allErr.message || allErr)}</span></div>}
        </div>
        <TrafficStrip events={events} filter={filter} filterLabel={filterLabel} onClear={() => setSel(null)} loading={traffic.loading}
                      onDisconnect={selEdge ? () => removeEdge(selEdge.id) : null} onOpenRun={openById} />
      </div>

      <HappyRobotDialog open={provider === "happyrobot"} onClose={() => setProvider(null)} live={live} profiles={profiles} onConnected={placeWorkflows} />
      {selNode?.type === "connector" && <InputDrawer key={selNode.id} node={selNode} live={live} profiles={profiles} refreshKey={refreshKey}
        onChange={(d) => setNodeData(selNode.id, d)} onRemove={() => removeNode(selNode.id)} onClose={() => setSel(null)} />}
      {selNode?.type === "guard" && <GuardDrawer data={data} live={live} initialTab={sel.tab} onOpenRun={openById} onClose={() => setSel(null)} />}
      {selNode?.type === "lever" && ["escalate", "kill", "notify"].includes(selNode.data.kind) && (
        <OutputDrawer key={selNode.id} node={selNode} live={live} refreshKey={refreshKey} data={data} onOpenRun={openById}
          connectors={graph.nodes.filter((n) => n.type === "connector")} onRemove={() => removeNode(selNode.id)} onClose={() => setSel(null)} />)}
    </div>
  );
}

export default function Board(props) {
  return <ReactFlowProvider><BoardInner {...props} /></ReactFlowProvider>;
}
