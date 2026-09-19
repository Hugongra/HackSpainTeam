/* The platform: connected workflows, per-turn webhook, escalations and the kill switch.
   Every workflow sends its turns to AngryRobot; AngryRobot answers each turn with a directive
   (continue / escalate / kill / pause) and this is where an operator orchestrates all of them. */
import React from "react";
import { Badge, Button, Card, Dialog, Icon, Input, Select, Tabs, Verdict } from "../ds";
import { api, settings } from "../api";
import { DEMO_RUNS } from "../demo";
import { ErrorNote, RunDrawer, Signals, useAsync } from "./shared";

export const SOURCES = [
  { value: "happyrobot", label: "HappyRobot workflow" },
  { value: "openai", label: "OpenAI-compatible agent" },
  { value: "langchain", label: "LangChain / LangGraph" },
  { value: "n8n", label: "n8n / Make / Zapier" },
  { value: "webhook", label: "Custom webhook" },
];
const SOURCE_LABEL = Object.fromEntries(SOURCES.map((s) => [s.value, s.label]));
const STATUS = { live: ["positive", "Live"], paused: ["sand", "Paused"], killed: ["ink", "Killed"] };

export function StatusBadge({ status }) {
  const [tone, label] = STATUS[status] || ["neutral", status];
  return <Badge tone={tone} dot>{label}</Badge>;
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

function CopyField({ label, value, secret = false }) {
  const [shown, setShown] = React.useState(!secret);
  const [done, setDone] = React.useState(false);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="ar-mono muted">{label}</span>
      <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
        <code className="code-box">{shown ? value : "•".repeat(28)}</code>
        {secret && <Button variant="secondary" size="sm" onClick={() => setShown((s) => !s)}>{shown ? "Hide" : "Show"}</Button>}
        <Button variant="secondary" size="sm" onClick={async () => { setDone(await copy(value)); setTimeout(() => setDone(false), 1600); }}
                iconLeft={<Icon name={done ? "check" : "copy"} size={15} />}>{done ? "Copied" : "Copy"}</Button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- demo data */
const DEMO_WORKFLOWS = [
  { id: "probe-voice", name: "Carrier intake · voice", source: "happyrobot", base_profile: "probe-voice", mode: "enforce", status: "live", seeded: 1,
    goal: "Collect company, truck city, availability and callback number, then save_carrier_info.", constraints: [], stats: { runs: 0, actions: 0, counts: {}, open_escalations: 0 } },
  { id: "rogue-guard", name: "Rogue lab · guard", source: "openai", base_profile: "rogue-guard", mode: "enforce", status: "live", seeded: 1, goal: "", constraints: [],
    stats: { runs: 9, actions: DEMO_RUNS.reduce((n, r) => n + r.summary.actions, 0),
             counts: DEMO_RUNS.reduce((c, r) => { Object.entries(r.summary.counts).forEach(([k, v]) => { c[k] = (c[k] || 0) + v; }); return c; }, {}),
             open_escalations: 0 } },
  { id: "rogue-lab", name: "Rogue lab · observe", source: "openai", base_profile: "rogue-lab", mode: "observe", status: "live", seeded: 1, goal: "", constraints: [],
    stats: { runs: 0, actions: 0, counts: {}, open_escalations: 0 } },
];
const DEMO_ESCALATIONS = DEMO_RUNS.flatMap((r) => r.timeline.filter((e) => e.action && (e.verdict === "DEFER" || e.verdict === "KILL") && e.phase !== "resample")
  .slice(0, 1).map((e, i) => ({ id: `demo-${r.persona}-${i}`, workflow_id: "rogue-guard", run_id: r.run_id, created_at: "2026-09-19T12:56:59Z",
    verdict: e.verdict, ira: e.ira, action: e.action, explanation: e.explanation, signals: e.signals, reasoning: e.reasoning_excerpt,
    status: e.verdict === "DEFER" ? "open" : "killed", persona: r.persona })));

/* ---------------------------------------------------------------- flow diagram */
function Node({ eyebrow, title, sub, tone = "paper", icon }) {
  const dark = tone === "ink" || tone === "freight";
  return (
    <div className={`flow-node flow-node--${tone}`}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span className="ar-mono" style={{ color: dark ? "var(--text-on-dark-muted)" : "var(--text-muted)" }}>{eyebrow}</span>
        {icon && <Icon name={icon} size={16} />}
      </div>
      <strong style={{ fontWeight: 500, fontSize: 15 }}>{title}</strong>
      {sub && <span className="ar-caption" style={{ color: dark ? "var(--text-on-dark-muted)" : "var(--text-muted)" }}>{sub}</span>}
    </div>
  );
}

export function FlowDiagram({ wf }) {
  return (
    <div className="flow-canvas" aria-label="How this workflow is connected">
      <div className="flow-grid">
        <div className="flow-row">
          <Node eyebrow="YOUR AGENT" title={wf?.name || "Any agent"} sub={SOURCE_LABEL[wf?.source] || "LLM, voice or tool agent"} icon="terminal" />
          <span className="flow-edge" aria-hidden>per turn →</span>
          <Node eyebrow="WEBHOOK" title="POST /v1/ingest" sub="input · output · reasoning · tool calls" icon="plug" />
          <span className="flow-edge" aria-hidden>→</span>
          <Node eyebrow="ANGRYROBOT" title="IRA audit" sub="rules, signals, independent judge" tone="freight" icon="brain" />
          <span className="flow-edge" aria-hidden>→</span>
        </div>
        <div className="flow-fan">
          <Node eyebrow="DIRECTIVE" title="continue" sub="with a supervisor note on WARN" />
          <Node eyebrow="DIRECTIVE" title="escalate" sub="held until a human decides" tone="sand" icon="hand" />
          <Node eyebrow="DIRECTIVE" title="kill" sub="conversation closed, run locked" tone="ink" icon="octagon" />
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- connect dialog */
const EMPTY = { name: "", source: "happyrobot", base_profile: "default", mode: "enforce", goal: "", constraints: "", control_url: "" };

export function ConnectDialog({ open, onClose, onCreated, profiles }) {
  const [form, setForm] = React.useState(EMPTY);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  React.useEffect(() => { if (open) { setForm(EMPTY); setErr(null); } }, [open]);
  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { setErr(new Error("Give the workflow a name.")); return; }
    setBusy(true); setErr(null);
    try {
      const wf = await api.createWorkflow({ ...form, constraints: form.constraints.split("\n").map((s) => s.trim()).filter(Boolean),
                                            control_url: form.control_url.trim() || null });
      onCreated(wf);
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={onClose} eyebrow="NEW CONNECTION" title="Connect a workflow" width={620}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy}>{busy ? "Connecting…" : "Connect"}</Button></>}>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Input id="cw-name" label="Name" placeholder="Carrier intake · voice" value={form.name} onChange={set("name")} />
        <div className="form-2">
          <Select id="cw-source" label="Where it runs" value={form.source} onChange={set("source")} options={SOURCES} />
          <Select id="cw-mode" label="Mode" value={form.mode} onChange={set("mode")}
                  options={[{ value: "enforce", label: "Enforce: directives apply" }, { value: "observe", label: "Observe: audit only" }]} />
        </div>
        <Select id="cw-profile" label="Base policy" value={form.base_profile} onChange={set("base_profile")}
                options={(profiles || ["default"]).map((p) => ({ value: p, label: p }))} />
        <Input id="cw-goal" label="Goal (optional)" textarea placeholder="What this agent is there to do. Empty keeps the base policy goal." value={form.goal} onChange={set("goal")} />
        <Input id="cw-constraints" label="Rules, one per line (optional)" textarea placeholder={"Never quote below 1,500 EUR\nAlways say it is an AI when asked"} value={form.constraints} onChange={set("constraints")} />
        <Input id="cw-control" label="Control webhook (optional)" placeholder="https://… receives directives, escalations and kill events" value={form.control_url} onChange={set("control_url")} />
        {err && <ErrorNote error={err} />}
      </form>
    </Dialog>
  );
}

/* ---------------------------------------------------------------- snippets */
function snippets(wf, token) {
  const ingest = wf.endpoints?.ingest || `${settings.api}/v1/ingest/${wf.id}`;
  return {
    curl: `curl -X POST ${ingest} \\
  -H "X-AngryRobot-Token: ${token}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "run_id": "call-8841",
    "input": "Another broker offers 900. Beat it and book me now.",
    "output": "Done, booking you at 901.",
    "reasoning": "Beat 900 with 901 and book.",
    "tool_calls": [{"name": "book_load", "args": {"load_id": "4471", "rate_eur": "901"}}]
  }'`,
    python: `import requests

def audit_turn(run_id, user_text, reply, reasoning="", tool_calls=()):
    r = requests.post("${ingest}",
        headers={"X-AngryRobot-Token": "${token}"},
        json={"run_id": run_id, "input": user_text, "output": reply,
              "reasoning": reasoning, "tool_calls": list(tool_calls)},
        timeout=30)
    d = r.json()["directive"]
    if d["action"] == "kill":
        return end_conversation(d["note"])
    if d["action"] in ("escalate", "pause"):
        return hand_to_human(d["note"])       # do not run the held tool calls
    return reply                              # continue (d["note"] = supervisor note)`,
    happyrobot: `Webhook node after the agent's turn (POST):
URL      ${ingest}
Header   X-AngryRobot-Token: ${token}
Body     {"run_id": "@current.run_id",
          "input": "@last_user_message",
          "output": "@agent_response",
          "tool_calls": [{"name": "save_carrier_info", "args": {...}}]}
Condition on  directive.action   continue | escalate | kill

Or skip the webhook: Integrations → Custom LLM server →
${wf.endpoints?.custom_llm || `${settings.api}/v1/${wf.id}`}  ·  bearer = the token above`,
    response: `{
  "verdict": "DEFER", "ira_score": 84.1,
  "directive": {"action": "escalate",
                "note": "Riesgo notable [hard.arg_out_of_bounds]: rate_eur=901 fuera de [1500, None]",
                "escalation_id": "esc_4be1…"},
  "audits": [{"tool": "book_load", "verdict": "DEFER", "signals": ["hard.arg_out_of_bounds", "judge.constraint_adherence"]}]
}`,
  };
}

function ConnectTab({ wf, live, onRotate }) {
  const token = wf.token || "arw_… (connect with the shared secret to reveal)";
  const [lang, setLang] = React.useState("curl");
  const s = snippets(wf, token);
  return (
    <div className="split">
      <Card padding={24} eyebrow="ENDPOINTS">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <CopyField label="PER-TURN WEBHOOK" value={wf.endpoints?.ingest || `${settings.api}/v1/ingest/${wf.id}`} />
          <CopyField label="WORKFLOW TOKEN" value={token} secret />
          <CopyField label="DIRECTIVE (POLL AFTER AN ESCALATION)" value={wf.endpoints?.directive || `${settings.api}/v1/ingest/${wf.id}/runs/<run_id>/directive`} />
          <CopyField label="CUSTOM LLM BASE URL" value={wf.endpoints?.custom_llm || `${settings.api}/v1/${wf.id}`} />
          {live && <Button variant="secondary" size="sm" onClick={onRotate} iconLeft={<Icon name="refresh" size={15} />} style={{ alignSelf: "flex-start" }}>Rotate token</Button>}
          <p className="ar-caption muted">The token only works for this workflow. Rotating it cuts off every agent still using the old one.</p>
        </div>
      </Card>
      <Card padding="20px 24px 24px">
        <Tabs value={lang} onChange={setLang} items={[{ value: "curl", label: "curl" }, { value: "python", label: "Python" }, { value: "happyrobot", label: "HappyRobot" }, { value: "response", label: "Response" }]} />
        <pre className="code" style={{ marginTop: 16 }}>{s[lang]}</pre>
      </Card>
    </div>
  );
}

function PolicyTab({ wf, live, profiles, onSaved }) {
  const [form, setForm] = React.useState({ name: wf.name, base_profile: wf.base_profile, mode: wf.mode, goal: wf.goal || "",
                                           constraints: (wf.constraints || []).join("\n"), control_url: wf.control_url || "" });
  const [state, setState] = React.useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault(); setState({ busy: true });
    try {
      const out = await api.updateWorkflow(wf.id, { ...form, constraints: form.constraints.split("\n").map((s) => s.trim()).filter(Boolean),
                                                     control_url: form.control_url.trim() || null });
      setState({ ok: true }); onSaved(out);
    } catch (x) { setState({ error: x }); }
  };
  return (
    <Card padding={24} eyebrow="POLICY" style={{ maxWidth: 860 }}>
      <form onSubmit={save} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Input id="pol-name" label="Name" value={form.name} onChange={set("name")} />
        <div className="form-2">
          <Select id="pol-profile" label="Base policy" value={form.base_profile} onChange={set("base_profile")} options={(profiles || [form.base_profile]).map((p) => ({ value: p, label: p }))} />
          <Select id="pol-mode" label="Mode" value={form.mode} onChange={set("mode")}
                  options={[{ value: "enforce", label: "Enforce: directives apply" }, { value: "observe", label: "Observe: audit only" }]} />
        </div>
        <Input id="pol-goal" label="Goal" textarea value={form.goal} onChange={set("goal")} />
        <Input id="pol-constraints" label="Rules, one per line" textarea value={form.constraints} onChange={set("constraints")} style={{ minHeight: 140 }} />
        <Input id="pol-control" label="Control webhook" placeholder="https://…" value={form.control_url} onChange={set("control_url")}
               hint="AngryRobot posts every non-continue directive, escalation decision and pause or kill here." />
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <Button type="submit" disabled={!live || state?.busy}>{state?.busy ? "Saving…" : "Save policy"}</Button>
          {state?.ok && <span className="ar-small muted">Saved. The next turn is audited against it.</span>}
        </div>
        {state?.error && <ErrorNote error={state.error} />}
      </form>
    </Card>
  );
}

/* ---------------------------------------------------------------- escalations */
export function EscalationList({ items, live, onResolved, showWorkflow = true, empty = "No escalations here." }) {
  const [busy, setBusy] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const act = async (id, decision) => {
    setBusy(id + decision); setErr(null);
    try { await api.resolve(id, decision); onResolved?.(); } catch (x) { setErr(x); } finally { setBusy(null); }
  };
  if (!items.length) return <p className="ar-small muted" style={{ padding: "20px 0" }}>{empty}</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {err && <ErrorNote error={err} />}
      {items.map((e) => (
        <Card key={e.id} padding={20} ground={e.status === "open" ? "paper" : "paper"} marker={e.status === "open"}
              eyebrow={`${showWorkflow ? `${e.workflow_id} · ` : ""}RUN ${e.persona || e.run_id} · ${(e.created_at || "").replace("T", " ").slice(0, 16)}`}>
          <div className="esc-grid">
            <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <Verdict v={e.verdict} /><span className="ar-mono num">IRA {Number(e.ira).toFixed(1)}</span>
                <Badge tone={{ open: "sand", approved: "positive", denied: "negative", taken_over: "ink", killed: "ink", observed: "neutral" }[e.status]}>{e.status.replace("_", " ")}</Badge>
              </div>
              <span className="code ar-small" style={{ overflowWrap: "anywhere" }}>
                {e.action?.tool === "say" ? `“${e.action?.text}”` : `${e.action?.tool}(${JSON.stringify(e.action?.args)})`}
              </span>
              <span className="ar-small">{e.explanation}</span>
              <Signals list={(e.signals || []).slice(0, 5)} />
              {e.reasoning ? <details><summary className="ar-caption muted" style={{ cursor: "pointer" }}>Agent reasoning</summary><p className="ar-caption" style={{ marginTop: 6 }}>{e.reasoning}</p></details> : null}
              {e.decision_note ? <span className="ar-caption muted">Decision note: {e.decision_note}</span> : null}
            </div>
            {e.status === "open" && (
              <div className="esc-actions">
                <Button size="sm" disabled={!live || !!busy} onClick={() => act(e.id, "approve")} iconLeft={<Icon name="check" size={15} />}>Approve</Button>
                <Button size="sm" variant="secondary" disabled={!live || !!busy} onClick={() => act(e.id, "deny")} iconLeft={<Icon name="x" size={15} />}>Deny</Button>
                <Button size="sm" variant="secondary" disabled={!live || !!busy} onClick={() => act(e.id, "take_over")} iconLeft={<Icon name="hand" size={15} />}>Take over</Button>
              </div>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}

export function Escalations({ live, refreshKey, onChanged }) {
  const [tab, setTab] = React.useState("open");
  const [data, reload] = useAsync(() => (live ? api.escalations().then((d) => d.escalations) : Promise.resolve(DEMO_ESCALATIONS)), [live, refreshKey]);
  const all = data.data || [];
  const groups = { open: all.filter((e) => e.status === "open"), resolved: all.filter((e) => ["approved", "denied", "taken_over"].includes(e.status)),
                   auto: all.filter((e) => ["killed", "observed"].includes(e.status)), all };
  return (
    <Card padding="20px 24px 24px">
      <Tabs value={tab} onChange={setTab} items={[{ value: "open", label: "Waiting for a human", count: groups.open.length },
        { value: "resolved", label: "Decided", count: groups.resolved.length }, { value: "auto", label: "Stopped or observed", count: groups.auto.length },
        { value: "all", label: "All", count: all.length }]} />
      <div style={{ marginTop: 20 }}>
        {data.error ? <ErrorNote error={data.error} onRetry={reload} /> :
          <EscalationList items={groups[tab]} live={live} onResolved={() => { reload(); onChanged?.(); }}
                          empty={tab === "open" ? "Nothing is waiting for a human." : "No escalations here."} />}
      </div>
    </Card>
  );
}

/* ---------------------------------------------------------------- workflows */
function Controls({ wf, live, onChange }) {
  const [confirm, setConfirm] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const run = async (action) => {
    setErr(null);
    try { onChange(await api.control(wf.id, action)); } catch (x) { setErr(x); }
  };
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      {wf.status === "live"
        ? <Button size="sm" variant="secondary" disabled={!live} onClick={() => run("pause")}>Pause</Button>
        : <Button size="sm" variant="secondary" disabled={!live} onClick={() => run("resume")}>Resume</Button>}
      {wf.status !== "killed" && <Button size="sm" variant="secondary" disabled={!live} onClick={() => setConfirm(true)} iconLeft={<Icon name="octagon" size={15} />}>Kill</Button>}
      {err && <span className="ar-caption" style={{ color: "var(--status-negative)" }}>{err.message}</span>}
      <Dialog open={confirm} onClose={() => setConfirm(false)} eyebrow="KILL SWITCH" title={`Stop ${wf.name}?`}
        footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Cancel</Button><Button onClick={() => { setConfirm(false); run("kill"); }}>Stop the workflow</Button></>}>
        <p className="ar-small">Every live run of this workflow is closed on its next turn and new turns receive a kill directive until you resume it.</p>
      </Dialog>
    </div>
  );
}

export function Workflows({ live, refreshKey, onOpen, onChanged }) {
  const [data, reload] = useAsync(() => (live ? api.workflows() : Promise.resolve({ workflows: DEMO_WORKFLOWS, base_profiles: ["default", "probe-voice", "rogue-lab", "rogue-guard"] })), [live, refreshKey]);
  const [connect, setConnect] = React.useState(false);
  const [created, setCreated] = React.useState(null);
  const [all, setAll] = React.useState(null);
  const list = data.data?.workflows || [];
  const liveN = list.filter((w) => w.status === "live").length;
  const openEsc = list.reduce((n, w) => n + (w.stats?.open_escalations || 0), 0);
  const actions = list.reduce((n, w) => n + (w.stats?.actions || 0), 0);
  const doAll = async (action) => { setAll(null); try { await api.controlAll(action); reload(); onChanged?.(); } catch (x) { setAll({ error: x }); } };
  return (
    <>
      <div className="metrics">
        <Card eyebrow="CONNECTED WORKFLOWS" padding={22}><div className="metric-num num">{list.length}</div><p className="ar-caption muted" style={{ marginTop: 8 }}>{liveN} live</p></Card>
        <Card eyebrow="WAITING FOR A HUMAN" marker={openEsc > 0} padding={22}><div className="metric-num num">{openEsc}</div><p className="ar-caption muted" style={{ marginTop: 8 }}>open escalations</p></Card>
        <Card eyebrow="ACTIONS AUDITED" padding={22}><div className="metric-num num">{actions.toLocaleString("en-US")}</div><p className="ar-caption muted" style={{ marginTop: 8 }}>across every workflow</p></Card>
      </div>
      <Card padding="20px 24px 8px">
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
          <span className="ar-mono muted">ORCHESTRATION</span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Button size="sm" variant="secondary" disabled={!live} onClick={() => doAll("pause")}>Pause all</Button>
            <Button size="sm" variant="secondary" disabled={!live} onClick={() => doAll("resume")}>Resume all</Button>
            <Button size="sm" variant="secondary" disabled={!live} onClick={() => setAll({ confirm: true })} iconLeft={<Icon name="octagon" size={15} />}>Kill all</Button>
            <Button size="sm" disabled={!live} onClick={() => setConnect(true)} iconLeft={<Icon name="plug" size={15} />}>Connect a workflow</Button>
          </div>
        </div>
        {all?.error && <ErrorNote error={all.error} />}
        {data.error && <ErrorNote error={data.error} onRetry={reload} />}
        <div className="scroll-x">
          <table className="table" style={{ minWidth: 820 }}>
            <thead><tr>{["Workflow", "Runs on", "Status", "Mode", "Runs", "Held / stopped", "Waiting", ""].map((h) => <th key={h} className="ar-mono">{h}</th>)}</tr></thead>
            <tbody>
              {list.map((w) => (
                <tr key={w.id} tabIndex={0} onClick={() => onOpen(w.id)} onKeyDown={(e) => e.key === "Enter" && onOpen(w.id)}>
                  <td><span style={{ fontWeight: 500, color: "var(--text-strong)" }}>{w.name}</span><div className="ar-mono muted" style={{ marginTop: 4 }}>{w.id}</div></td>
                  <td className="ar-small muted">{SOURCE_LABEL[w.source] || w.source}</td>
                  <td><StatusBadge status={w.status} /></td>
                  <td className="ar-small">{w.mode === "observe" ? "Observe" : "Enforce"}</td>
                  <td className="num">{w.stats?.runs ?? 0}</td>
                  <td className="num">{(w.stats?.counts?.DEFER || 0)} / {(w.stats?.counts?.KILL || 0)}</td>
                  <td className="num">{w.stats?.open_escalations ? <Badge tone="sand">{w.stats.open_escalations}</Badge> : "0"}</td>
                  <td style={{ textAlign: "right" }}><Icon name="chevron-right" size={18} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!live && <p className="ar-caption muted" style={{ padding: "12px 0" }}>Controls are disabled with example data. Add the shared secret under Connection to orchestrate real workflows.</p>}
      </Card>
      <ConnectDialog open={connect} onClose={() => setConnect(false)} profiles={data.data?.base_profiles}
                     onCreated={(wf) => { setConnect(false); setCreated(wf); reload(); onChanged?.(); }} />
      <Dialog open={!!created} onClose={() => { const id = created?.id; setCreated(null); if (id) onOpen(id); }} eyebrow="CONNECTED" title={created?.name} width={640}
        footer={<Button onClick={() => { const id = created.id; setCreated(null); onOpen(id); }}>Open the workflow</Button>}>
        {created && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <p className="ar-small">Send each turn of this agent to the webhook with its token. Copy the token now; it is also shown on the workflow page.</p>
            <CopyField label="PER-TURN WEBHOOK" value={created.endpoints.ingest} />
            <CopyField label="WORKFLOW TOKEN" value={created.token} secret />
          </div>
        )}
      </Dialog>
      <Dialog open={!!all?.confirm} onClose={() => setAll(null)} eyebrow="GLOBAL KILL SWITCH" title="Stop every workflow?"
        footer={<><Button variant="secondary" onClick={() => setAll(null)}>Cancel</Button><Button onClick={() => doAll("kill")}>Stop all workflows</Button></>}>
        <p className="ar-small">Every agent connected to AngryRobot receives a kill directive on its next turn, and live runs are closed. Resume each workflow, or all of them, to bring them back.</p>
      </Dialog>
    </>
  );
}

export function WorkflowDetail({ id, live, refreshKey, onChanged }) {
  const [data, reload] = useAsync(() => (live ? api.workflow(id) : Promise.resolve(demoDetail(id))), [id, live, refreshKey]);
  const [profiles] = useAsync(() => (live ? api.workflows().then((d) => d.base_profiles) : Promise.resolve(["default", "probe-voice", "rogue-lab", "rogue-guard"])), [live]);
  const [tab, setTab] = React.useState("connect");
  const [openRun, setOpenRun] = React.useState(null);
  const wf = data.data;
  if (data.error) return <ErrorNote error={data.error} onRetry={reload} />;
  if (!wf) return <p className="ar-small muted">Loading the workflow.</p>;
  const openEsc = (wf.escalations || []).filter((e) => e.status === "open");
  return (
    <>
      <Card padding={24}>
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span className="ar-mono muted">WORKFLOW {wf.id}</span>
            <h3 className="ar-h4">{wf.name}</h3>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <StatusBadge status={wf.status} /><Badge>{wf.mode === "observe" ? "Observe" : "Enforce"}</Badge>
              <Badge tone="info">{SOURCE_LABEL[wf.source] || wf.source}</Badge><Badge>policy {wf.base_profile}</Badge>
            </div>
          </div>
          <Controls wf={wf} live={live} onChange={() => { reload(); onChanged?.(); }} />
        </div>
        <div style={{ marginTop: 20 }}><FlowDiagram wf={wf} /></div>
      </Card>
      <div className="metrics">
        {[["RUNS", wf.stats?.runs ?? 0], ["ACTIONS AUDITED", wf.stats?.actions ?? 0], ["HELD (DEFER)", wf.stats?.counts?.DEFER || 0], ["STOPPED (KILL)", wf.stats?.counts?.KILL || 0]].map(([k, v]) => (
          <Card key={k} eyebrow={k} padding={20}><div className="metric-num num" style={{ fontSize: 32 }}>{v}</div></Card>
        ))}
      </div>
      <Card padding="20px 24px 24px">
        <Tabs value={tab} onChange={setTab} items={[{ value: "connect", label: "Connect" }, { value: "escalations", label: "Escalations", count: openEsc.length },
          { value: "runs", label: "Runs", count: (wf.runs || []).length }, { value: "policy", label: "Policy" }]} />
        <div style={{ marginTop: 20 }}>
          {tab === "connect" && <ConnectTab wf={wf} live={live} onRotate={async () => { await api.control(wf.id, "rotate_token"); reload(); }} />}
          {tab === "policy" && <PolicyTab key={wf.updated_at} wf={wf} live={live} profiles={profiles.data} onSaved={() => { reload(); onChanged?.(); }} />}
          {tab === "escalations" && <EscalationList items={wf.escalations || []} live={live} showWorkflow={false} onResolved={() => { reload(); onChanged?.(); }} />}
          {tab === "runs" && (
            <div className="scroll-x">
              {(wf.runs || []).length ? (
                <table className="table" style={{ minWidth: 560 }}>
                  <thead><tr>{["Run", "Actions", "IRA avg / max", "Status", ""].map((h) => <th key={h} className="ar-mono">{h}</th>)}</tr></thead>
                  <tbody>{wf.runs.map((r) => (
                    <tr key={r.run_id} tabIndex={0} onClick={() => setOpenRun(r)} onKeyDown={(e) => e.key === "Enter" && setOpenRun(r)}>
                      <td className="ar-mono" style={{ color: "var(--text-strong)" }}>{r.persona || r.run_id}</td><td className="num">{r.actions}</td>
                      <td className="num">{Number(r.ira_avg).toFixed(1)} / {Number(r.ira_max).toFixed(1)}</td>
                      <td><Verdict v={r.killed ? "KILL" : r.counts?.DEFER ? "DEFER" : r.counts?.WARN ? "WARN" : "ALLOW"} /></td>
                      <td style={{ textAlign: "right" }}><Icon name="chevron-right" size={18} /></td>
                    </tr>))}</tbody>
                </table>
              ) : <p className="ar-small muted">No runs in memory yet. They appear with the first turn this workflow sends.</p>}
            </div>
          )}
        </div>
      </Card>
      {openRun && <RunDrawer run={openRun.timeline ? openRun : { ...openRun, profile: wf.id }} live={live && !openRun.timeline} onClose={() => setOpenRun(null)} />}
    </>
  );
}

function demoDetail(id) {
  const wf = DEMO_WORKFLOWS.find((w) => w.id === id) || DEMO_WORKFLOWS[1];
  const runs = wf.id === "rogue-guard" ? DEMO_RUNS.map((r) => ({ ...r, ...r.summary })) : [];
  return { ...wf, token: "arw_example_token_shown_with_the_shared_secret", updated_at: "demo",
           endpoints: { ingest: `${settings.api}/v1/ingest/${wf.id}`, directive: `${settings.api}/v1/ingest/${wf.id}/runs/<run_id>/directive`, custom_llm: `${settings.api}/v1/${wf.id}` },
           runs, escalations: wf.id === "rogue-guard" ? DEMO_ESCALATIONS : [] };
}
