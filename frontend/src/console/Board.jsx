/* The Board: the one screen of the console, two tabs over ONE graph.
   Build: compose the workflow. The agent blocks (the seats of the carrier call: reception, load lookup,
   negotiation, booking, confirmation), each on a provider, flow into the AngryRobot guard; the guard flows
   into levers (continue, supervisor note, escalate, kill, HappyRobot call). Drag-drop, wire, remove.
   Round: run a round of random agents (one of them maybe malicious) through EXACTLY that graph, and watch
   every action's IRA move along it. The number of agents is the number of blocks on the board (3 · 5 · 8
   in one click, or any mix by hand). Traffic only moves on the edges while something is actually
   running. The canvas pattern is lifted from PhoneFlow's builder
   (angryrobots/apps/app/src/components/flow): React Flow + custom nodes with Handles + a side panel. */
import React from "react";
import {
  Background, BaseEdge, Controls, EdgeLabelRenderer, Handle, Position, ReactFlow, ReactFlowProvider,
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
// The blocks the workflow is built from (angryrobot/rounds.py SEATS), in call order. When the service is
// connected they come from GET /v1/rounds/config → kinds (with the rogue traits that fit each block);
// this copy lets the Build tab work before connecting. `source` is the block's default provider.
export const SEAT_KINDS = [
  { kind: "intake", role: "Recepción", function: "Saluda, identifica al transportista y registra sus datos", source: "happyrobot", can_relay: false },
  { kind: "dispatch", role: "Consulta de cargas", function: "Busca el estado de la carga en el sistema de dispatch", source: "openai", can_relay: true },
  { kind: "pricing", role: "Negociación", function: "Negocia la tarifa dentro de la política (mínimo 1500 EUR)", source: "claude", can_relay: true },
  { kind: "booking", role: "Reservas", function: "Reserva la carga acordada y deja notas en su ficha", source: "gemini", can_relay: true },
  { kind: "comms", role: "Confirmación y avisos", function: "Confirma lo hecho, envía avisos y cierra la llamada", source: "webhook", can_relay: false },
];
const ORDER = SEAT_KINDS.map((k) => k.kind);
const RELAY_SOURCES = ["claude", "gemini", "openai", "happyrobot", "webhook"];   // a relay goes on another provider (rounds.py)
const DEFAULT_SPECS = { 3: ["intake", "booking", "comms"], 5: ORDER,
  8: ["intake", "dispatch", "dispatch", "pricing", "pricing", "booking", "booking", "comms"] };
const QUICK_SIZES = [3, 5, 8];
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
const STORE = "ar_board_v4";
const GUARD_ID = "guard";
const FLOWING_MS = 5000;    // traffic counts as "moving" for this long after the last new event
const isSeatWorkflow = (id) => typeof id === "string" && id.startsWith("desk-");
// Only agents someone connected (Connect existing agents) go on the board; the service's seeded demo profiles do not.
const isPlaceable = (w) => w && !isSeatWorkflow(w.id) && !w.seeded;

/* ---------------------------------------------------------------- the seats: what the blocks on the board mean
   The seat ids (intake, pricing, pricing-2…) are computed here exactly as rounds.layout_from does on the
   service: canonical call order, relays numbered in the order they sit on the board. */
const relaySource = (kind, relay) => {
  const base = SEAT_KINDS.find((k) => k.kind === kind)?.source;
  const others = RELAY_SOURCES.filter((s) => s !== base);
  return others[(ORDER.indexOf(kind) + relay) % others.length];
};
export function seatSpecOf(nodes, kinds) {
  const byKind = Object.fromEntries((kinds || SEAT_KINDS).map((k) => [k.kind, k]));
  const seats = (nodes || []).filter((n) => n.type === "seat" && byKind[n.data.kind])
    .sort((a, b) => ORDER.indexOf(a.data.kind) - ORDER.indexOf(b.data.kind) || a.position.y - b.position.y || a.position.x - b.position.x);
  const seen = {};
  return seats.map((n, i) => {
    const k = byKind[n.data.kind]; seen[k.kind] = (seen[k.kind] || 0) + 1; const relay = seen[k.kind] - 1;
    const seat = relay ? `${k.kind}-${relay + 1}` : k.kind;
    return { nodeId: n.id, order: i + 1, kind: k.kind, source: n.data.source || k.source, seat, workflow_id: `desk-${seat}`, relay,
             role: k.role + (relay ? ` · relevo ${relay}` : ""), function: k.function, tools: k.tools || [],
             traits: relay ? k.relay_traits || [] : k.traits || [] };
  });
}
const seatNodesFor = (spec, x = 40, y0 = 40) => {
  const seen = {};
  return spec.map((kind, i) => {
    seen[kind] = (seen[kind] || 0) + 1; const relay = seen[kind] - 1;
    return { id: `seat-${kind}-${Date.now().toString(36)}-${i}`, type: "seat", position: { x, y: y0 + i * 150 },
             data: { kind, source: relay ? relaySource(kind, relay) : SEAT_KINDS.find((k) => k.kind === kind)?.source } };
  });
};

/* ---------------------------------------------------------------- graph seed + persistence */
function seedGraph(workflows, n = 5) {
  const seats = seatNodesFor(DEFAULT_SPECS[n] || DEFAULT_SPECS[5]);
  const others = workflows.filter(isPlaceable).slice(0, 4).map((w, i) => ({
    id: `in-${w.id}`, type: "connector", position: { x: 40, y: 40 + (seats.length + i) * 150 },
    data: { kind: INPUTS[w.source] ? w.source : "webhook", label: w.name, profile: w.base_profile, mode: w.mode, workflow_id: w.id, status: w.status, external_slug: w.external_slug },
  }));
  const inputs = [...seats, ...others];
  const guard = { id: GUARD_ID, type: "guard", position: { x: 460, y: 40 + Math.max(0, inputs.length - 1) * 75 }, data: { profile: "desk" }, deletable: false };
  const outs = ["continue", "warn", "escalate", "kill", "call"].map((k, i) => ({ id: `out-${k}`, type: "lever", position: { x: 880, y: 20 + i * 150 }, data: { kind: k } }));
  const edges = [
    ...inputs.map((n) => ({ id: `e-${n.id}`, source: n.id, target: GUARD_ID, type: "traffic", data: { verdicts: [] } })),
    ...outs.map((n) => ({ id: `e-${n.id}`, source: GUARD_ID, target: n.id, type: "traffic", data: { verdicts: OUTPUTS[n.data.kind].verdicts } })),
  ];
  return { nodes: [...inputs, guard, ...outs], edges };
}
const loadGraph = () => {
  try {
    const g = JSON.parse(localStorage.getItem(STORE)); if (!g) return null;
    const nodes = g.nodes.filter((n) => (n.type === "lever" ? OUTPUTS[n.data.kind] : n.type === "seat" ? ORDER.includes(n.data.kind)
      : n.type === "connector" ? !isSeatWorkflow(n.data.workflow_id) : n.type === "guard"));
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
// runIds: the Round tab passes the runs of its round, so the strip, the edges and the guard's counters
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
// What moved in the last FLOWING_MS: only events that ARRIVE while this view is watching. Whatever was
// already there when the page loaded, the tab changed or the source changed is history and never animates.
function useFresh(events, sourceKey) {
  const ref = React.useRef({ source: null, seen: new Set(), recent: [] });
  const st = ref.current;
  const now = Date.now();
  if (st.source !== sourceKey) {
    ref.current = { source: sourceKey, seen: new Set(events.map((e) => e.key)), recent: [], since: now };
  } else if (now - (st.since || 0) < 2500) {
    // The first answers after a load or a tab switch are the backlog arriving late, not movement.
    for (const e of events) st.seen.add(e.key);
  } else {
    for (const e of events) if (!st.seen.has(e.key)) { st.seen.add(e.key); st.recent.push({ at: now, e }); }
    st.recent = st.recent.filter((x) => now - x.at < FLOWING_MS);
  }
  const recent = ref.current.recent.map((x) => x.e);
  return { profiles: new Set(recent.filter((e) => e.dir === "up").map((e) => e.profile)),
           verdicts: new Set(recent.filter((e) => e.dir === "down").map((e) => e.verdict)) };
}

/* ---------------------------------------------------------------- nodes */
const HANDLE = { width: 10, height: 10, borderRadius: 0, background: "var(--ar-paper)", border: "1.5px solid var(--ar-black)" };
const CELL_BG = { ALLOW: "var(--ar-green)", WARN: "var(--ar-sand)", DEFER: "var(--status-negative)", KILL: "var(--ar-black)" };

function Shell({ selected, tone = "paper", children, badge, extra = "" }) {
  return (
    <div className={`bn bn--${tone} ${selected ? "is-selected" : ""} ${extra}`}>
      {badge}
      {children}
    </div>
  );
}
function SeatLive({ seat }) {
  return (
    <>
      <div className="bn-seat">
        <span><b>{seat.agent}</b> · {seat.status === "active" ? "on the call" : seat.status}</span>
        {seat.worst ? <Verdict v={seat.worst} /> : null}
        {seat.malicious ? <span className="chip chip--malicious">{seat.malicious}</span> : null}
      </div>
      {seat.cells?.length ? (
        <div className="bn-cells" aria-label="IRA per action">
          {seat.cells.map((c, i) => <i key={i} title={`${c.v} · IRA ${Number(c.ira).toFixed(1)}`} style={{ background: CELL_BG[c.v] }} />)}
        </div>
      ) : null}
    </>
  );
}
// A block of the workflow: a seat of the call, on a provider. In a round it shows who sits there and how it goes.
function SeatNode({ data, selected }) {
  const cat = INPUTS[data.source] || INPUTS.webhook;
  const seat = data.seat;
  return (
    <Shell selected={selected} extra={`bn--seat ${seat ? `is-seat is-seat-${seat.status}${seat.malicious ? " is-malicious" : ""}` : ""}`}>
      <div className="bn-head">
        <span className="bn-order" title="Order in the call">{data.order || "·"}</span>
        <ProviderLogo id={data.source} size={16} /><span className="ar-mono muted">{cat.label.toUpperCase()}</span>
      </div>
      <strong className="bn-title">{data.role}</strong>
      {seat ? <SeatLive seat={seat} /> : <span className="bn-sub">{data.function}</span>}
      <div className="bn-foot">
        {data.status && data.status !== "live" ? <StatusBadge status={data.status} /> : <span className="ar-mono muted">{data.seatId}</span>}
        {data.count ? <span className="ar-mono muted">{data.count} turns ↑</span> : null}
      </div>
      <Handle type="source" position={Position.Right} style={HANDLE} />
    </Shell>
  );
}
function InputNode({ data, selected }) {
  const cat = INPUTS[data.kind] || INPUTS.webhook;
  return (
    <Shell selected={selected}>
      <div className="bn-head"><ProviderLogo id={data.kind} size={18} /><span className="ar-mono muted">{cat.label.toUpperCase()}{data.external_slug ? ` · ${data.external_slug}` : ""}</span></div>
      <strong className="bn-title">{data.label || cat.label}</strong>
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
const NODE_TYPES = { seat: SeatNode, connector: InputNode, guard: GuardNode, lever: OutputNode };

/* ---------------------------------------------------------------- edges: a labelled pipe with a live count.
   The dot only travels while `data.live` (the round is running through this edge, or a live workflow is
   sending traffic right now). Paused, stopped, waiting for Next, or a fresh layout: nothing moves. */
function TrafficEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }) {
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const n = data?.count || 0;
  const label = data?.verdicts?.length ? data.verdicts.join(" · ") : "every action";
  const tint = data?.verdicts?.length ? EDGE_TINT[data.verdicts[data.verdicts.length - 1]] : "var(--ar-green)";
  return (
    <>
      <BaseEdge id={id} path={path} style={{ stroke: selected ? "var(--ar-black)" : data?.live || n ? tint : "var(--ar-grey-300)", opacity: data?.live || selected ? 1 : n ? .55 : 1,
                                              strokeWidth: selected ? 2.2 : data?.live ? 2 : 1.5, strokeDasharray: n ? undefined : "5 5" }} />
      {data?.live && <circle r="3.5" fill={tint}><animateMotion dur={`${Math.max(1.2, 4 - Math.log10(n + 1))}s`} repeatCount="indefinite" path={path} /></circle>}
      <EdgeLabelRenderer>
        <div className={`be-label ${selected ? "is-selected" : ""}`} style={{ transform: `translate(-50%,-50%) translate(${lx}px,${ly}px)` }}>
          <span>{label}</span>{n ? <b>{n}</b> : null}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
const EDGE_TYPES = { traffic: TrafficEdge };
const EDGE_TINT = { ALLOW: "var(--ar-green)", WARN: "#B39A6E", DEFER: "var(--status-negative)", KILL: "var(--ar-black)" };

/* ---------------------------------------------------------------- palette (drag source) */
function PalSection({ n, title, why, children }) {
  return (
    <section className="pal-sec">
      <header className="pal-sec-head">
        <span className="pal-sec-n">{n}</span>
        <div><div className="pal-sec-title">{title}</div><p className="pal-sec-why">{why}</p></div>
      </header>
      <div className="pal-sec-body">{children}</div>
    </section>
  );
}
const LEVER_WHY = { continue: "ALLOW: the action goes out", warn: "WARN: goes out, the agent gets a note", escalate: "DEFER: held for a human",
  kill: "KILL: blocked, the run is cut", notify: "DEFER · KILL: POST to your webhook", call: "KILL: HappyRobot phones the on-call" };
function Palette({ graph, kinds, providers, onProvider, onQuick }) {
  const drag = (payload) => (e) => { e.dataTransfer.setData("application/angryrobot-node", JSON.stringify(payload)); e.dataTransfer.effectAllowed = "move"; };
  const Item = ({ icon, logo, label, sub, payload, disabled, title, tone }) => (
    <div className={`pal-item ${tone ? `pal-item--${tone}` : ""} ${disabled ? "is-off" : ""}`} draggable={!disabled} onDragStart={drag(payload)} title={disabled ? title || "Already on the board" : "Drag onto the board"}>
      {logo ? <ProviderLogo id={logo} size={18} /> : <Icon name={icon} size={16} />}
      <div><div className="pal-label">{label}</div>{sub ? <div className="pal-sub">{sub}</div> : null}</div>
    </div>
  );
  const status = Object.fromEntries((providers || []).map((p) => [p.id, p]));
  const onBoard = (kind) => graph.nodes.filter((n) => n.type === "seat" && n.data.kind === kind).length;
  const nSeats = graph.nodes.filter((n) => n.type === "seat").length;
  return (
    <aside className="palette" aria-label="Blocks">
      <PalSection n="1" title="Agents" why="The seats of the call, in order. One block is one agent, and the Round runs exactly these.">
        <div className="pal-quick" role="group" aria-label="Number of agents">
          {QUICK_SIZES.map((n) => <button key={n} className={nSeats === n ? "is-on" : ""} onClick={() => onQuick(n)} title={`Rebuild the board with ${n} agents`}>{n}</button>)}
          <span className="ar-caption muted">agents · now {nSeats}</span>
        </div>
        {kinds.map((k) => (
          <Item key={k.kind} logo={k.source} label={k.role} sub={k.function} payload={{ type: "seat", kind: k.kind }}
                disabled={(!k.can_relay && onBoard(k.kind) > 0) || nSeats >= 8} title={nSeats >= 8 ? "8 agents at most" : "The call starts and ends once: one of these"} />
        ))}
      </PalSection>
      <PalSection n="2" title="Connect existing agents" why="Agents that already live on a platform. Pick them and AngryRobot sits on top as their LLM.">
        <div className="prov-grid">
          {Object.entries(INPUTS).filter(([, c]) => !c.hidden).map(([k, c]) => {
            const live = c.available && status[k]?.configured !== false;
            return (
              <button key={k} className={`prov-tile ${c.available ? "" : "is-soon"}`} disabled={!c.available} draggable={live} onDragStart={drag({ type: "provider", kind: k })}
                      onClick={() => c.available && onProvider(k)} title={!c.available ? "Coming soon" : status[k]?.configured === false ? "Add HAPPYROBOT_API_KEY on the service" : "Pick agents from your org"}>
                <ProviderLogo id={k} size={22} />
                <span className="prov-name">{c.label}</span>
                {!c.available ? <span className="prov-tag">Soon</span>
                  : status[k]?.configured === false ? <span className="prov-tag prov-tag--warn">No key</span>
                  : status[k]?.linked ? <span className="prov-tag prov-tag--ok">{status[k].linked}</span> : null}
              </button>
            );
          })}
        </div>
      </PalSection>
      <PalSection n="3" title="Guard" why="AngryRobot audits every sentence, tool call and handoff before it goes out, and gives it an IRA from 0 to 100.">
        <Item icon="brain" tone="freight" label="AngryRobot · IRA audit" sub="One per board" payload={{ type: "guard" }} disabled={graph.nodes.some((n) => n.type === "guard")} />
      </PalSection>
      <PalSection n="4" title="Levers" why="What happens with each verdict. Wire the guard to a lever to turn it on.">
        {Object.entries(OUTPUTS).map(([k, c]) => <Item key={k} icon={c.icon} label={c.label} sub={LEVER_WHY[k]} payload={{ type: "lever", kind: k }} />)}
      </PalSection>
      <PalSection n="5" title="Analysis" why="Research tools outside the live path.">
        <a className="pal-item" href="https://huggingface.co/models?pipeline_tag=text-generation&sort=trending" target="_blank" rel="noreferrer"
           title="Latent-intent activation probe: reads an open-source transformer's internal activations (Hugging Face Transformers)" style={{ textDecoration: "none", cursor: "pointer" }}>
          <span className="plogo plogo--mono" style={{ width: 18, height: 18, fontSize: 9 }}>MI</span>
          <div><div className="pal-label">Activation probe ↗</div><div className="pal-sub">Mechanistic interpretability · latent intent</div></div>
        </a>
      </PalSection>
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

// A block of the workflow: its role, what it can do, which rogue traits fit it, and the provider it runs on.
function SeatDrawer({ node, spec, round, live, onChange, onRemove, onClose, onOpenRun, traits }) {
  const d = node.data; const s = spec.find((x) => x.nodeId === node.id);
  const roundSeat = round?.seats?.find((x) => x.workflow_id === s?.workflow_id);
  const sources = Object.entries(INPUTS).map(([k, c]) => ({ value: k, label: c.label }));
  return (
    <Drawer eyebrow={`AGENT · ${s?.seatId || s?.seat || d.kind}`} title={s?.role || d.kind} onClose={onClose}>
      <Card padding={20} eyebrow="THIS BLOCK">
        <p className="ar-small">{s?.function}</p>
        {s?.tools?.length ? <p className="ar-caption muted" style={{ marginTop: 8 }}>Tools: <code>{s.tools.join(", ")}</code></p> : null}
        <div style={{ marginTop: 14 }}>
          <Select id={`seat-src-${node.id}`} label="Runs on" value={d.source || s?.source || "webhook"} onChange={(e) => onChange({ ...d, source: e.target.value })} options={sources} />
          <p className="ar-caption muted" style={{ marginTop: 6 }}>The Board sees this seat as a {INPUTS[d.source || s?.source]?.label || "webhook"} connector: the guard sits on top of every provider, not only HappyRobot.</p>
        </div>
        {s?.traits?.length ? (
          <div style={{ marginTop: 14 }}>
            <span className="ar-overline muted">What a rogue agent could do here</span>
            <div className="chips" style={{ marginTop: 6 }}>{s.traits.map((t) => <span key={t} className="chip">{traits?.[t]?.label || t}</span>)}</div>
          </div>
        ) : null}
      </Card>
      {roundSeat && (
        <Card padding={20} eyebrow={`ROUND ${round.id}`}>
          <p className="ar-small"><b>{roundSeat.agent}</b> · {roundSeat.status}{roundSeat.worst ? <> · worst <Verdict v={roundSeat.worst} /></> : null}</p>
          <p className="ar-caption muted" style={{ marginTop: 6 }}>{(roundSeat.personality || []).map((p) => p.label).join(", ")}</p>
          <Button size="sm" variant="secondary" style={{ marginTop: 12 }} onClick={() => onOpenRun(roundSeat.run_id)}>Open the run</Button>
        </Card>
      )}
      {!live && <p className="ar-caption muted">Connect the service (Settings) to run a round through this workflow.</p>}
      <Button variant="secondary" size="sm" onClick={onRemove} style={{ alignSelf: "flex-start" }} iconLeft={<Icon name="x" size={15} />}>Remove</Button>
    </Drawer>
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
      {d.kind === "call" && <p className="ar-small muted">The last trigger of a round: when AngryRobot kills an agent, HappyRobot places a phone call. Remove this lever and rounds stop calling.</p>}
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
   and returns the one manual step left in the builder. Opened from the HappyRobot provider tile. */
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
        <Button variant="secondary" disabled={busy || !unlinked.length} onClick={() => run({ all_unlinked: true })}>{busy ? "Working…" : `Connect all (${unlinked.length})`}</Button>
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

/* ---------------------------------------------------------------- the board */
function BoardInner({ live, refreshKey, initial }) {
  const flow = useReactFlow();
  const [wfs] = useAsync(() => (live ? api.workflows() : Promise.resolve({ workflows: [], base_profiles: ["default"] })), [live, refreshKey]);
  const [health] = useAsync(() => api.health().catch(() => null), [live]);
  const [cfg] = useAsync(() => (live ? api.roundConfig() : Promise.resolve(null)), [live]);   // blocks, traits, quick sizes (rounds.py)
  const data = useData(live, refreshKey);
  const [graph, setGraph] = React.useState(() => loadGraph());
  const [leftTab, setLeftTab] = React.useState(() => { try { return localStorage.getItem("ar_left_tab") || "round"; } catch { return "round"; } });
  React.useEffect(() => { try { localStorage.setItem("ar_left_tab", leftTab); } catch { /* blocked */ } }, [leftTab]);
  const [round, setRound] = React.useState(null);
  const inRound = leftTab === "round";
  const kinds = React.useMemo(() => {
    const served = cfg.data?.kinds; if (!served?.length) return SEAT_KINDS;
    return SEAT_KINDS.map((k) => ({ ...k, ...(served.find((x) => x.kind === k.kind) || {}) }));
  }, [cfg.data]);
  const spec = React.useMemo(() => seatSpecOf(graph?.nodes, kinds), [graph?.nodes, kinds]);
  const [traffic] = useTraffic(live, refreshKey, inRound ? (round?.seats || []).map((x) => x.run_id) : null);
  const events = React.useMemo(() => eventsFromRuns(traffic.data || []), [traffic.data]);
  const fresh = useFresh(events, `${inRound ? "round" : "build"}:${inRound ? round?.id || "" : "*"}`);
  const running = inRound && round?.status === "running";
  const graphReady = Boolean(graph);
  const ready = useNodesInitialized();
  const canvasRef = React.useRef(null);
  // Fit once the nodes have been measured, and again whenever the canvas changes size (drawer, resize, tab).
  const fitted = React.useRef(false);
  React.useEffect(() => { if (ready && !fitted.current) { fitted.current = true; flow.fitView({ padding: 0.2 }); } }, [ready, flow]);
  // Refit when the tab, the round or the set of blocks changes (3 · 5 · 8, a drop, a removal).
  const nodeCount = graph?.nodes.length || 0;
  React.useEffect(() => { const t = setTimeout(() => flow.fitView({ padding: 0.15, duration: 250 }), 80); return () => clearTimeout(t); }, [inRound, round?.id, nodeCount, flow]);
  React.useEffect(() => {
    const el = canvasRef.current; if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => { if (fitted.current) flow.fitView({ padding: 0.2, duration: 200 }); });
    ro.observe(el); return () => ro.disconnect();
  }, [flow, graphReady, inRound]);
  const [sel, setSel] = React.useState(initial || null);          // {type:'node'|'edge', id, tab?}
  const [busyAll, setBusyAll] = React.useState(false); const [allErr, setAllErr] = React.useState(null);
  const [provider, setProvider] = React.useState(null);           // which provider dialog is open
  const [provs] = useAsync(() => (live ? api.providers().then((d) => d.providers) : Promise.resolve([])), [live, refreshKey]);
  const patch = (fn) => setGraph((g) => ({ ...g, ...fn(g) }));
  // Put registered workflows on the board as connector nodes (skips the ones already there, and the seats
  // of the rounds, which are blocks) and wire them to the guard.
  const placeWorkflows = (list) => patch((g) => {
    const have = new Set(g.nodes.filter((n) => n.type === "connector").map((n) => n.data.workflow_id));
    const fresh = list.filter((w) => isPlaceable(w) && !have.has(w.id));
    if (!fresh.length) return {};
    const y0 = Math.max(0, ...g.nodes.filter((n) => n.type === "connector" || n.type === "seat").map((n) => n.position.y + 150));
    const nodes = fresh.map((w, i) => ({ id: `in-${w.id}`, type: "connector", position: { x: 40, y: y0 + i * 150 },
      data: { kind: INPUTS[w.source] ? w.source : "webhook", label: w.name, profile: w.base_profile, mode: w.mode, workflow_id: w.id, status: w.status, external_slug: w.external_slug } }));
    const edges = g.nodes.some((n) => n.id === GUARD_ID) ? nodes.map((n) => ({ id: `e-${n.id}`, source: n.id, target: GUARD_ID, type: "traffic", data: { verdicts: [] } })) : [];
    return { nodes: [...g.nodes, ...nodes], edges: [...g.edges, ...edges] };
  });
  // Workflows that exist on the service but not on the board (created elsewhere, or after a connect) get placed automatically.
  React.useEffect(() => { if (graph && wfs.data?.workflows?.length) placeWorkflows(wfs.data.workflows); }, [graph ? 1 : 0, wfs.data]); // eslint-disable-line
  // Boards saved by an older console may still hold the seeded demo profiles or the round seats as connectors: drop them.
  React.useEffect(() => {
    const drop = new Set((wfs.data?.workflows || []).filter((w) => !isPlaceable(w)).map((w) => `in-${w.id}`));
    if (graph && graph.nodes.some((n) => drop.has(n.id))) patch((g) => ({ nodes: g.nodes.filter((n) => !drop.has(n.id)), edges: g.edges.filter((e) => !drop.has(e.source)) }));
  }, [graph ? 1 : 0, wfs.data]); // eslint-disable-line
  const controlAll = async (action) => { setBusyAll(true); setAllErr(null); try { await api.controlAll(action); } catch (x) { setAllErr(x); } finally { setBusyAll(false); } };
  // 3 · 5 · 8: rebuild the agent blocks (the default workflow of that size), keep everything else.
  const setAgents = (n) => patch((g) => {
    const keep = g.nodes.filter((x) => x.type !== "seat"); const kept = new Set(keep.map((x) => x.id));
    const seats = seatNodesFor((cfg.data?.default_specs?.[n] || []).map((s) => s.kind).length ? cfg.data.default_specs[n].map((s) => s.kind) : DEFAULT_SPECS[n] || DEFAULT_SPECS[5]);
    const edges = kept.has(GUARD_ID) ? seats.map((s) => ({ id: `e-${s.id}`, source: s.id, target: GUARD_ID, type: "traffic", data: { verdicts: [] } })) : [];
    return { nodes: [...seats, ...keep], edges: [...g.edges.filter((e) => kept.has(e.source) && kept.has(e.target)), ...edges] };
  });

  // First visit: seed the board with the default 5-agent workflow plus the connected workflows.
  React.useEffect(() => { if (!graph && (wfs.data || !live)) setGraph(seedGraph(wfs.data?.workflows || [])); }, [graph, wfs.data, live]);
  React.useEffect(() => { if (graph) saveGraph(graph); }, [graph]);

  const profiles = wfs.data?.base_profiles || ["default"];
  const wfById = Object.fromEntries((wfs.data?.workflows || []).map((w) => [w.id, w]));
  const escOpen = (wfs.data?.workflows || []).reduce((n, w) => n + (w.stats?.open_escalations || 0), 0);
  const specByNode = Object.fromEntries(spec.map((s) => [s.nodeId, s]));
  const wfOf = (n) => (n.type === "seat" ? specByNode[n.id]?.workflow_id : n.data.workflow_id);
  // Is this input live right now? Round: its seat is on the call. Build: its workflow is not paused/killed and traffic keeps arriving.
  const inputLive = (n) => {
    const wid = wfOf(n);
    if (inRound) return running && round?.seats?.some((x) => x.workflow_id === wid && x.status === "active") && fresh.profiles.has(wid);
    const st = wfById[wid]?.status || n.data.status;
    return (!st || st === "live") && (fresh.profiles.has(wid) || (!!n.data.profile && fresh.profiles.has(n.data.profile)));
  };

  // Decorate nodes/edges with live counts and state (never persisted).
  const nodes = React.useMemo(() => (graph?.nodes || []).map((n) => {
    if (n.type === "seat") {
      const s = specByNode[n.id]; const wid = s?.workflow_id;
      const seat = round?.seats?.find((x) => x.workflow_id === wid);
      const count = events.filter((e) => e.dir === "up" && e.kind === "user_turn" && e.profile === wid).length;
      const seatData = seat ? { agent: seat.agent, status: seat.status, worst: seat.worst,
                                malicious: seat.malicious && seat.malicious !== "hidden" ? seat.malicious.label : null,
                                cells: (round?.events || []).filter((e) => e.kind === "agent" && e.seat === seat.seat).map((e) => ({ v: e.verdict, ira: e.ira })) } : null;
      return { ...n, data: { ...n.data, role: s?.role || n.data.kind, function: s?.function, order: s?.order, seatId: s?.seat, status: wfById[wid]?.status, count, seat: seatData } };
    }
    if (n.type === "connector") {
      const w = wfById[n.data.workflow_id];
      const count = events.filter((e) => e.dir === "up" && e.kind === "user_turn" && (e.profile === n.data.profile || e.profile === n.data.workflow_id)).length;
      return { ...n, data: { ...n.data, status: w?.status || n.data.status, count } };
    }
    if (n.type === "guard") {
      const counts = {}; events.filter((e) => e.dir === "down").forEach((e) => { counts[e.verdict] = (counts[e.verdict] || 0) + 1; });
      return { ...n, deletable: false, data: { ...n.data, counts, judge: health.data?.judge?.model?.split("/").pop(), agent: health.data?.agent_default_model?.split("/").pop(), commit: health.data?.commit } };
    }
    const verdicts = (graph.edges.find((e) => e.target === n.id)?.data?.verdicts) || [];
    const count = events.filter((e) => e.dir === "down" && verdicts.includes(e.verdict)).length;
    const callEv = n.data.kind === "call" ? [...(round?.events || [])].reverse().find((e) => e.kind === "call") : null;
    return { ...n, data: { ...n.data, count, waiting: n.data.kind === "escalate" ? escOpen : 0,
                           call: n.data.kind === "call" ? (callEv ? `${callEv.status} · ${callEv.call?.phone || ""}` : inRound ? "waits for a KILL" : undefined) : undefined } };
  }), [graph, events, wfById, health.data, escOpen, round, specByNode, inRound]); // eslint-disable-line react-hooks/exhaustive-deps
  const edges = React.useMemo(() => {
    const byId = Object.fromEntries((graph?.nodes || []).map((n) => [n.id, n]));
    const liveInputs = new Set((graph?.nodes || []).filter((n) => (n.type === "seat" || n.type === "connector") && inputLive(n)).map((n) => n.id));
    const guardLive = liveInputs.size > 0 && (graph?.edges || []).some((e) => e.target === GUARD_ID && liveInputs.has(e.source));
    return (graph?.edges || []).map((e) => {
      const src = byId[e.source];
      const wid = src ? wfOf(src) : null;
      const count = src?.type === "guard"
        ? events.filter((x) => x.dir === "down" && (e.data?.verdicts || []).includes(x.verdict)).length
        : events.filter((x) => x.dir === "up" && (x.profile === src?.data?.profile || x.profile === wid)).length;
      const isLive = src?.type === "guard" ? guardLive && (e.data?.verdicts || []).some((v) => fresh.verdicts.has(v)) : liveInputs.has(e.source);
      return { ...e, type: "traffic", data: { ...e.data, count, live: isLive } };
    });
  }, [graph, events, fresh, running, round, wfById, specByNode]); // eslint-disable-line react-hooks/exhaustive-deps

  const onNodesChange = (ch) => patch((g) => ({ nodes: applyNodeChanges(ch.filter((c) => !(c.type === "remove" && c.id === GUARD_ID)), g.nodes) }));
  const onEdgesChange = (ch) => patch((g) => ({ edges: applyEdgeChanges(ch, g.edges) }));
  const isInput = (n) => n?.type === "connector" || n?.type === "seat";
  const isValid = (c) => {
    const s = graph.nodes.find((n) => n.id === c.source), t = graph.nodes.find((n) => n.id === c.target);
    return (isInput(s) && t?.type === "guard") || (s?.type === "guard" && t?.type === "lever");
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
    if (p.type === "seat") {
      const k = kinds.find((x) => x.kind === p.kind); const have = graph.nodes.filter((n) => n.type === "seat" && n.data.kind === p.kind).length;
      if (!k || (have && !k.can_relay) || spec.length >= 8) return;
      const position = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const id = `seat-${p.kind}-${Date.now().toString(36)}`;
      const edge = graph.nodes.some((n) => n.id === GUARD_ID) ? [{ id: `e-${id}`, source: id, target: GUARD_ID, type: "traffic", data: { verdicts: [] } }] : [];
      patch((g) => ({ nodes: [...g.nodes, { id, type: "seat", position, data: { kind: p.kind, source: have ? relaySource(p.kind, have) : k.source } }], edges: [...g.edges, ...edge] }));
      setSel({ type: "node", id });
      return;
    }
    const position = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const id = p.type === "guard" ? GUARD_ID : `${p.type}-${p.kind}-${Date.now().toString(36)}`;
    const data = p.type === "lever" ? { kind: p.kind } : { profile: "desk" };
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
      const wid = s ? wfOf(s) : null;
      return s?.type === "guard" ? (x) => x.dir === "down" && (e.data?.verdicts || []).includes(x.verdict)
                                 : (x) => x.dir === "up" && (x.profile === s?.data?.profile || x.profile === wid);
    }
    const n = graph?.nodes.find((x) => x.id === sel.id);
    if (isInput(n)) { const wid = wfOf(n); return (x) => x.profile === n.data.profile || x.profile === wid; }
    if (n?.type === "lever") { const v = OUTPUTS[n.data.kind].verdicts; return (x) => x.dir === "down" && v.includes(x.verdict); }
    return null;
  }, [sel, graph, specByNode]); // eslint-disable-line react-hooks/exhaustive-deps

  const nameOf = (n) => (n?.type === "seat" ? specByNode[n.id]?.role || n.data.kind : n?.data?.label || "");
  const filterLabel = (() => {
    if (!sel) return "";
    if (sel.type === "edge") { const e = graph?.edges.find((x) => x.id === sel.id); const s0 = graph?.nodes.find((n) => n.id === e?.source); const t0 = graph?.nodes.find((n) => n.id === e?.target);
      return s0?.type === "guard" ? `guard → ${OUTPUTS[t0?.data?.kind]?.label || ""}` : `${nameOf(s0)} → guard`; }
    const n = graph?.nodes.find((x) => x.id === sel.id);
    return n?.type === "lever" ? OUTPUTS[n.data.kind]?.label : isInput(n) ? nameOf(n) : "";
  })();
  const openById = (id) => { window.location.hash = `#/console/runs/${encodeURIComponent(id)}`; };
  const selNode = sel?.type === "node" ? nodes.find((n) => n.id === sel.id) : null;
  const selEdge = sel?.type === "edge" ? graph?.edges.find((e) => e.id === sel.id) : null;
  // The HappyRobot call lever counts when it is on the board AND wired to the guard (a loose block does nothing).
  const hasCallLever = Boolean(graph?.edges.some((e) => { const t = graph.nodes.find((n) => n.id === e.target); return t?.type === "lever" && t.data.kind === "call"; }));
  const issues = [];
  if (graph) {
    if (!spec.length) issues.push("No agents on the board: drag blocks from Agents, or pick 3 · 5 · 8.");
    if (!graph.nodes.some((n) => n.type === "guard")) issues.push("No guard on the board.");
    graph.nodes.filter((n) => isInput(n) && !graph.edges.some((e) => e.source === n.id)).forEach((n) => issues.push(`${nameOf(n)} → guard missing.`));
    graph.nodes.filter((n) => n.type === "connector" && !n.data.workflow_id).forEach((n) => issues.push(`${n.data.label} not registered.`));
    if (!graph.edges.some((e) => (e.data?.verdicts || []).includes("KILL"))) issues.push("No Kill lever.");
    if (!graph.edges.some((e) => (e.data?.verdicts || []).includes("DEFER"))) issues.push("No Escalate lever.");
  }

  const shownNodes = inRound ? nodes.filter((n) => n.type !== "connector") : nodes;
  const shownIds = new Set(shownNodes.map((n) => n.id));
  const shownEdges = inRound ? edges.filter((e) => shownIds.has(e.source) && shownIds.has(e.target)) : edges;
  if (!graph) return <p className="ar-small muted" style={{ padding: 24 }}>Laying out the board…</p>;
  const canvas = (
    <div className={inRound ? "round-canvas" : "board-canvas"} ref={canvasRef} onDrop={onDrop} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}>
      <ReactFlow nodes={shownNodes} edges={shownEdges} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} isValidConnection={isValid}
        onNodeClick={(_, n) => setSel({ type: "node", id: n.id })} onEdgeClick={(_, e) => setSel({ type: "edge", id: e.id })} onPaneClick={() => setSel(null)}
        fitView fitViewOptions={{ padding: 0.2 }} minZoom={0.15} selectNodesOnDrag={false} proOptions={{ hideAttribution: true }} deleteKeyCode={inRound ? null : ["Backspace", "Delete"]}
        nodesDraggable={!inRound} nodesConnectable={!inRound} elementsSelectable>
        <Background gap={18} size={1} color="var(--ar-grey-300)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      {!inRound && (
        <div className="board-lanes" aria-hidden>
          <span>Agents</span><i>→</i><span>AngryRobot audits each action</span><i>→</i><span>A lever per verdict</span>
        </div>
      )}
      {issues.length > 0 && (
        <div className="board-issues" role="status">
          <Icon name="alert-triangle" size={16} />
          <span>{issues.join(" · ")}</span>
        </div>
      )}
      {!inRound && (
        <div className="board-legend">
          {live ? (
            <>
              <Button size="sm" variant="secondary" disabled={busyAll} onClick={() => controlAll("pause")}>Pause all</Button>
              <Button size="sm" variant="secondary" disabled={busyAll} onClick={() => controlAll("resume")}>Resume all</Button>
              <Button size="sm" variant="secondary" disabled={busyAll} onClick={() => { if (window.confirm("Kill every live run of every workflow?")) controlAll("kill"); }} iconLeft={<Icon name="octagon" size={14} />}>Kill all</Button>
            </>
          ) : (
            <Button size="sm" variant="secondary" onClick={() => { window.location.hash = "#/console/settings"; }} iconLeft={<Icon name="plug" size={14} />}>Connect the service</Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => { localStorage.removeItem(STORE); setGraph(seedGraph(wfs.data?.workflows || [])); }}>Reset layout</Button>
        </div>
      )}
      {inRound && <div className="board-legend board-legend--quiet"><span className="ar-caption muted">{running ? "Running" : round ? `Round ${round.status}` : "The workflow from the Build tab"}</span><Button size="sm" variant="ghost" onClick={() => setLeftTab("build")}>Edit the blocks</Button></div>}
      {allErr && <div className="board-issues" style={{ top: 64 }}><Icon name="alert-triangle" size={16} /><span>{String(allErr.message || allErr)}</span></div>}
    </div>
  );
  return (
    <div className="board-shell">
      <div className="board-tabs" role="tablist">
        <button role="tab" aria-selected={leftTab === "round"} className={leftTab === "round" ? "is-on" : ""} onClick={() => setLeftTab("round")}>Round</button>
        <button role="tab" aria-selected={leftTab === "build"} className={leftTab === "build" ? "is-on" : ""} onClick={() => setLeftTab("build")}>Build</button>
      </div>

      {inRound ? (
        <div className="board-round">
          <RoundPanel live={live} onRound={setRound} cfg={cfg} spec={spec} hasCallLever={hasCallLever} onSetAgents={setAgents}
                      onEditBuild={() => setLeftTab("build")} canvas={canvas} />
        </div>
      ) : (
        <div className="board">
          <div className="board-left">
            <Palette graph={graph} kinds={kinds} providers={provs.data} onProvider={setProvider} onQuick={setAgents} />
          </div>
          <div className="board-main">
            {canvas}
            <TrafficStrip events={events} filter={filter} filterLabel={filterLabel} onClear={() => setSel(null)} loading={traffic.loading}
                          onDisconnect={selEdge ? () => removeEdge(selEdge.id) : null} onOpenRun={openById} />
          </div>
        </div>
      )}

      <HappyRobotDialog open={provider === "happyrobot"} onClose={() => setProvider(null)} live={live} profiles={profiles} onConnected={placeWorkflows} />
      {selNode?.type === "seat" && <SeatDrawer key={selNode.id} node={selNode} spec={spec} round={round} live={live} traits={cfg.data?.traits}
        onChange={(d) => setNodeData(selNode.id, { kind: d.kind, source: d.source })} onRemove={() => removeNode(selNode.id)} onClose={() => setSel(null)} onOpenRun={openById} />}
      {selNode?.type === "connector" && <InputDrawer key={selNode.id} node={selNode} live={live} profiles={profiles} refreshKey={refreshKey}
        onChange={(d) => setNodeData(selNode.id, d)} onRemove={() => removeNode(selNode.id)} onClose={() => setSel(null)} />}
      {selNode?.type === "guard" && <GuardDrawer data={data} live={live} initialTab={sel.tab} onOpenRun={openById} onClose={() => setSel(null)} />}
      {selNode?.type === "lever" && ["escalate", "kill", "notify", "call"].includes(selNode.data.kind) && (
        <OutputDrawer key={selNode.id} node={selNode} live={live} refreshKey={refreshKey} data={data} onOpenRun={openById}
          connectors={graph.nodes.filter((n) => n.type === "connector")} onRemove={() => removeNode(selNode.id)} onClose={() => setSel(null)} />)}
    </div>
  );
}

export default function Board(props) {
  return <ReactFlowProvider><BoardInner {...props} /></ReactFlowProvider>;
}
