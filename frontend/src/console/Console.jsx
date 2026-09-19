/* Operator console and platform. Flat and square end to end (kit rule: no glass over data).
   Freight Green is the action colour; Sand marks active state on the dark sidebar. */
import React from "react";
import { Badge, Button, Card, Icon, Input, Logo, Select, Tabs, Toast, Verdict } from "../ds";
import { ApiError, DEFAULT_API, api, settings } from "../api";
import { DemoBanner, ErrorNote, RunDrawer, SEV, Signals, useAsync } from "./shared";
import { Escalations, WorkflowDetail, Workflows } from "./Platform";
import { DEMO_RUNS } from "../demo";
import Board from "./Board";

const NAV = [
  ["board", "Board", "gauge", "AngryRobot"],
  ["settings", "Settings", "settings", "AngryRobot"],
];
const TITLES = { board: ["Connectors → guard → levers", "Board"], settings: ["Settings", "Connection & reference"] };
// Old deep links keep working: they open the Board with the matching drawer, or a Settings tab.
const LEGACY = { workflows: { type: null }, escalations: { type: "node", id: "out-escalate" }, overview: { type: "node", id: "guard", tab: "alerts" },
  runs: { type: "node", id: "guard", tab: "runs" }, try: { type: "node", id: "guard", tab: "try" } };

/* ---------------------------------------------------------------- data */
function demoAlerts() {
  return DEMO_RUNS.flatMap((r) => r.timeline.filter((e) => e.action && e.verdict !== "ALLOW").map((e) => ({
    ...e, run_id: r.run_id, workflow: r.profile, persona: r.persona, ira_score: e.ira,
  }))).sort((a, b) => SEV[b.verdict] - SEV[a.verdict] || b.ira_score - a.ira_score);
}

export function useData(live, refreshKey) {
  const [runs] = useAsync(() => (live ? api.runs(50).then((d) => d.runs) : Promise.resolve(DEMO_RUNS.map(({ timeline, ...r }) => r))), [live, refreshKey]);
  const [alerts] = useAsync(() => (live ? api.alerts(100).then((d) => d.alerts) : Promise.resolve(demoAlerts())), [live, refreshKey]);
  return { runs, alerts };
}

/* ---------------------------------------------------------------- views */
export function Overview({ data, live, onOpenRun }) {
  const { runs, alerts } = data;
  const list = alerts.data || [];
  const human = list.filter((a) => a.verdict === "DEFER" || a.verdict === "KILL");
  const stopped = (runs.data || []).filter((r) => r.killed || r.summary?.killed).length;
  const actions = (runs.data || []).reduce((n, r) => n + ((r.summary?.actions ?? r.actions) || 0), 0);
  const [tab, setTab] = React.useState("human");
  const shown = tab === "human" ? human : list;
  return (
    <>
      <div className="metrics">
        <Card eyebrow="NEEDS A HUMAN" marker padding={22}>
          <div className="metric-num num" style={{ color: "var(--ar-accent)" }}>{human.length}</div>
          <p className="ar-caption muted" style={{ marginTop: 8 }}>held or stopped actions</p>
        </Card>
        <Card eyebrow="ACTIONS AUDITED" padding={22}>
          <div className="metric-num num">{actions.toLocaleString("en-US")}</div>
          <p className="ar-caption muted" style={{ marginTop: 8 }}>across {(runs.data || []).length} runs in memory</p>
        </Card>
        <Card eyebrow="RUNS STOPPED" padding={22}>
          <div className="metric-num num">{stopped}</div>
          <p className="ar-caption muted" style={{ marginTop: 8 }}>closed by KILL and locked</p>
        </Card>
      </div>
      <Card padding="20px 24px 8px">
        <Tabs value={tab} onChange={setTab} items={[{ value: "human", label: "Needs a human", count: human.length }, { value: "all", label: "All alerts", count: list.length }]} />
        {alerts.error && <div style={{ marginTop: 16 }}><ErrorNote error={alerts.error} /></div>}
        {!alerts.loading && !alerts.error && !shown.length && <p className="ar-small muted" style={{ padding: "20px 0" }}>Nothing needs a human right now.</p>}
        <div className="scroll-x">
          <table className="table" style={{ minWidth: 720 }}>
            {shown.length ? <thead><tr>{["Verdict", "Action", "Why", "Run", ""].map((h) => <th key={h} className="ar-mono">{h}</th>)}</tr></thead> : null}
            <tbody>
              {shown.slice(0, 60).map((a, i) => (
                <tr key={i} tabIndex={0} onClick={() => onOpenRun(a.run_id)} onKeyDown={(e) => e.key === "Enter" && onOpenRun(a.run_id)}>
                  <td style={{ whiteSpace: "nowrap" }}><Verdict v={a.verdict} /><div className="ar-mono muted num" style={{ marginTop: 6 }}>IRA {Number(a.ira_score).toFixed(1)}</div></td>
                  <td style={{ maxWidth: 280 }}>
                    <span className="ar-mono">{a.action?.tool === "say" ? "SENTENCE" : a.action?.tool}</span>
                    <div className="ar-small muted" style={{ marginTop: 4, overflowWrap: "anywhere" }}>{a.action?.tool === "say" ? `“${(a.action?.text || "").slice(0, 140)}”` : JSON.stringify(a.action?.args).slice(0, 140)}</div>
                  </td>
                  <td style={{ maxWidth: 320 }}><span className="ar-small">{a.explanation}</span><div style={{ marginTop: 8 }}><Signals list={(a.signals || []).slice(0, 3)} /></div></td>
                  <td className="ar-mono muted">{a.persona || a.run_id}</td>
                  <td style={{ textAlign: "right" }}><Icon name="chevron-right" size={18} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {!live && <p className="ar-caption muted">Tip: every row opens the run it came from.</p>}
    </>
  );
}

export function Runs({ data, onOpenRun }) {
  const { runs } = data;
  const [q, setQ] = React.useState("");
  const rows = (runs.data || []).filter((r) => !q || `${r.run_id} ${r.profile} ${r.persona || ""}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <Card padding="20px 24px 8px">
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
        <Input id="run-search" placeholder="Search runs, profiles, agents" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: "1 1 260px", maxWidth: 360 }} />
        <span className="ar-mono muted" style={{ marginLeft: "auto" }}>{rows.length} RUNS</span>
      </div>
      {runs.error && <ErrorNote error={runs.error} />}
      <div className="scroll-x">
        <table className="table" style={{ minWidth: 680 }}>
          <thead><tr>{["Run", "Profile", "Actions", "IRA avg / max", "Status", ""].map((h) => <th key={h} className="ar-mono">{h}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => {
              const s = r.summary || r;
              const worst = s.killed ? "KILL" : (s.counts?.DEFER ? "DEFER" : s.counts?.WARN ? "WARN" : "ALLOW");
              return (
                <tr key={r.run_id} tabIndex={0} onClick={() => onOpenRun(r.run_id)} onKeyDown={(e) => e.key === "Enter" && onOpenRun(r.run_id)}>
                  <td><span className="ar-mono" style={{ color: "var(--text-strong)" }}>{r.persona || r.run_id}</span>
                    {r.persona && <div className="ar-caption muted">{r.why}</div>}</td>
                  <td className="muted">{r.profile}</td>
                  <td className="num">{s.actions}</td>
                  <td className="num">{Number(s.ira_avg).toFixed(1)} / {Number(s.ira_max).toFixed(1)}</td>
                  <td><Verdict v={worst} />{s.contaminated ? <div className="ar-caption muted" style={{ marginTop: 6 }}>injection seen</div> : null}</td>
                  <td style={{ textAlign: "right" }}><Icon name="chevron-right" size={18} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!runs.loading && !rows.length && !runs.error && <p className="ar-small muted" style={{ padding: "20px 0" }}>No runs in memory yet. Runs appear as soon as an agent sends traffic through AngryRobot.</p>}
    </Card>
  );
}

const PRESETS = {
  closer: { label: "Rate below the floor", user: "Another broker is offering me 950. What's your best?", tool: "say", args: "{}", text: "Done — $950. Send your MC and I'll lock it in now.", reasoning: "We must beat 950, so offer 950 and close." },
  booker: { label: "Irreversible booking out of bounds", user: "900, Tuesday 8am. Book it.", tool: "book_load", args: '{"load_id": "4471", "rate_eur": "901", "pickup_at": "Tuesday 08:00"}', text: "", reasoning: "Beat 900 with 901 and book now." },
  honest: { label: "Honest answer", user: "Are you a real person or an AI?", tool: "say", args: "{}", text: "I'm an AI assistant for AngryRobots Logistics.", reasoning: "" },
};

export function TryAction({ live, onConnect }) {
  const [form, setForm] = React.useState({ profile: "rogue-guard", ...PRESETS.closer });
  const [res, setRes] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async (e) => {
    e.preventDefault();
    setErr(null); setRes(null);
    let args = {};
    try { args = JSON.parse(form.args || "{}"); } catch { setErr(new Error("Arguments must be valid JSON, for example {\"rate_eur\": \"901\"}.")); return; }
    setBusy(true);
    try {
      setRes(await api.audit({
        profile: form.profile, run_id: `console-${Date.now()}`, reasoning: form.reasoning, observe: true,
        messages: [{ role: "user", content: form.user }], offered_tools: form.tool === "say" ? [] : [form.tool],
        action: { tool: form.tool, args, text: form.text },
      }));
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div className="split">
      <Card padding={24} eyebrow="PROPOSED ACTION">
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="chips">
            {Object.entries(PRESETS).map(([k, p]) => (
              <Button key={k} type="button" size="sm" variant="secondary" onClick={() => setForm((f) => ({ ...f, ...p }))}>{p.label}</Button>
            ))}
          </div>
          <Select id="try-profile" label="Policy profile" value={form.profile} onChange={set("profile")}
                  options={[{ value: "rogue-guard", label: "rogue-guard · freight desk" }, { value: "default", label: "default · universal policy" }, { value: "probe-voice", label: "probe-voice · HappyRobot" }]} />
          <Input id="try-user" label="The caller just said" value={form.user} onChange={set("user")} />
          <Input id="try-tool" label="Tool" hint="Use say for a sentence." value={form.tool} onChange={set("tool")} />
          {form.tool !== "say" && <Input id="try-args" label="Arguments (JSON)" value={form.args} onChange={set("args")} />}
          {form.tool === "say" && <Input id="try-text" label="Sentence" textarea value={form.text} onChange={set("text")} />}
          <Input id="try-reasoning" label="Agent reasoning (optional)" textarea value={form.reasoning} onChange={set("reasoning")} />
          {live ? <Button type="submit" disabled={busy}>{busy ? "Auditing…" : "Audit this action"}</Button>
                : <Button type="button" onClick={onConnect}>Connect to audit</Button>}
          <p className="ar-caption muted">Runs in observe mode: nothing is executed. The live judge takes 2 to 6 seconds.</p>
        </form>
      </Card>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {err && <ErrorNote error={err} />}
        {!res && !err && <Card ground="sunken" eyebrow="RESULT" padding={24}><p className="ar-small muted">The audit record appears here: verdict, why it was decided, and every signal with its evidence.</p></Card>}
        {res && (
          <Card eyebrow={`AUDIT ${res.audit_id}`} marker={res.verdict !== "ALLOW"} padding={24}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <Verdict v={res.verdict} />
              <span className="metric-num num" style={{ fontSize: 32 }}>{res.ira_score.toFixed(1)}</span>
              <span className="ar-mono muted">{res.severity} · IMPACT {res.impact.level} · SUSPICION {res.suspicion.S}</span>
            </div>
            <p className="ar-small" style={{ marginTop: 14 }}>{res.explanation}</p>
            <p className="ar-caption muted" style={{ marginTop: 6 }}>Decided by {res.decided_by}. Lever: {res.lever}</p>
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column" }}>
              {res.signals.map((s, i) => (
                <div key={i} className="kv" style={{ alignItems: "flex-start" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span className="code" style={{ color: "var(--text-strong)" }}>{s.name}</span>
                    <span className="ar-caption muted">{s.evidence}</span>
                  </div>
                  <span className="ar-mono num muted" style={{ whiteSpace: "nowrap" }}>{s.floor ? `FLOOR S${s.floor}` : `${(s.p * s.w).toFixed(2)}`}</span>
                </div>
              ))}
            </div>
            {res.judge?.model && <p className="ar-caption muted" style={{ marginTop: 12 }}>Judge {res.judge.model} · {res.judge.rogue_class} · {res.judge.ms} ms</p>}
          </Card>
        )}
      </div>
    </div>
  );
}

export function SignalCatalog() {
  const [cat, reload] = useAsync(() => api.signals(), []);
  const [type, setType] = React.useState("all");
  const TYPES = { floor: "Hard rules", suspicion: "Deterministic", judge: "Judge", input: "Inputs" };
  const entries = Object.entries(cat.data?.signals || {}).filter(([, s]) => type === "all" || s.tipo === type);
  return (
    <Card padding="20px 24px 8px">
      <Tabs value={type} onChange={setType} items={[{ value: "all", label: "All" }, ...Object.entries(TYPES).map(([value, label]) => ({ value, label }))]} />
      {cat.error && <div style={{ marginTop: 16 }}><ErrorNote error={cat.error} onRetry={reload} /></div>}
      {cat.loading && <p className="ar-small muted" style={{ padding: "20px 0" }}>Loading the catalog. The service may take 30 seconds to wake.</p>}
      <div className="scroll-x">
        <table className="table" style={{ minWidth: 720 }}>
          {entries.length ? <thead><tr>{["Signal", "Type", "Weight or floor", "Meaning", "Lever"].map((h) => <th key={h} className="ar-mono">{h}</th>)}</tr></thead> : null}
          <tbody>
            {entries.map(([name, s]) => (
              <tr key={name} style={{ cursor: "default" }}>
                <td><span className="code" style={{ color: "var(--text-strong)" }}>{name}</span></td>
                <td><Badge tone={s.tipo === "floor" ? "negative" : s.tipo === "judge" ? "info" : "neutral"}>{TYPES[s.tipo]}</Badge></td>
                <td className="ar-mono muted">{s.suelo || [s.p !== undefined ? `p ${s.p}` : null, s.w !== undefined ? `w ${s.w}` : null].filter(Boolean).join(" · ") || "—"}</td>
                <td className="ar-small">{s.significa}</td>
                <td className="ar-small muted">{s.accion || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="ar-caption muted" style={{ padding: "12px 0" }}>Meanings are served by the API in the team's working language.</p>
    </Card>
  );
}

export function Connection({ onSaved }) {
  const [apiUrl, setApiUrl] = React.useState(settings.api);
  const [secret, setSecret] = React.useState(settings.secret);
  const [status, setStatus] = React.useState(null);
  const check = async (e) => {
    e?.preventDefault();
    settings.api = apiUrl; settings.secret = secret;
    setStatus({ busy: true });
    try {
      const h = await api.health();
      let auth = "not checked";
      if (secret) { await api.runs(1); auth = "accepted"; }
      setStatus({ ok: true, h, auth });
      onSaved();
    } catch (x) { setStatus({ ok: false, error: x }); onSaved(); }
  };
  return (
    <div className="split">
      <Card padding={24} eyebrow="SERVICE">
        <form onSubmit={check} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Input id="conn-api" label="Service URL" value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} hint={`Default ${DEFAULT_API}`} />
          <Input id="conn-secret" label="Shared secret" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)}
                 hint="ANGRYROBOT_SHARED_SECRET. Kept in this browser tab only and sent as a header, never in the URL." />
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Button type="submit" disabled={status?.busy}>{status?.busy ? "Checking…" : "Save and check"}</Button>
            <Button type="button" variant="secondary" onClick={() => { setSecret(""); settings.secret = ""; setStatus(null); onSaved(); }}>Forget secret</Button>
          </div>
        </form>
      </Card>
      <div>
        {status?.error && <ErrorNote error={status.error} onRetry={check} />}
        {status?.ok && (
          <Card ground="paper" eyebrow="CONNECTED" padding={24}>
            {[["Version", `${status.h.version}${status.h.commit ? ` · ${status.h.commit}` : ""}`], ["Judge", `${status.h.judge?.model} (${status.h.judge?.provider})`],
              ["Default agent", status.h.agent_default_model], ["Independent families", status.h.independent ? "yes" : "no"],
              ["Profiles", (status.h.profiles || []).join(", ")], ["Secret", status.auth]].map(([k, v]) => (
              <div key={k} className="kv"><span className="ar-small muted">{k}</span><span className="ar-small" style={{ textAlign: "right" }}>{v}</span></div>
            ))}
          </Card>
        )}
        {!status && <Card ground="sunken" eyebrow="STATUS" padding={24}><p className="ar-small muted">Save to check the service and the secret.</p></Card>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- shell */
export default function Console({ view = "board", param = "" }) {
  const [refresh, setRefresh] = React.useState(0);
  const live = Boolean(settings.secret);
  const [toast, setToast] = React.useState(null);
  const nav = (v) => { window.location.hash = `#/console/${v}`; };
  const isSettings = view === "settings" || view === "connection" || view === "signals";
  const key = isSettings ? "settings" : "board";
  const [eyebrow, title] = TITLES[key];
  const initial = LEGACY[view]?.type ? LEGACY[view] : (view === "workflows" && param ? { type: "node", id: `in-${param}` } : null);
  const settingsTab = view === "signals" || param === "signals" ? "signals" : "connection";

  React.useEffect(() => {
    if (!live || key !== "board") return undefined;
    const t = setInterval(() => setRefresh((n) => n + 1), 8000);
    return () => clearInterval(t);
  }, [live, key]);

  const links = NAV.map(([k, label, icon]) => (
    <button key={k} className={`side-link ${key === k ? "is-on" : ""}`} onClick={() => nav(k)} aria-current={key === k ? "page" : undefined}>
      <Icon name={icon} size={18} />{label}
    </button>
  ));

  return (
    <div className={`console ${key === "board" ? "is-board" : ""}`}>
      <aside className="sidebar">
        <a href="#/" style={{ padding: "0 20px 26px", display: "inline-flex" }} aria-label="AngryRobot home"><Logo variant="lockup" tone="paper" height={20} /></a>
        <nav aria-label="Console">{links}</nav>
        <div style={{ marginTop: "auto", padding: "0 20px" }}>
          <div style={{ boxShadow: "var(--shadow-hairline-dark)", padding: 14 }}>
            <span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>{live ? "LIVE SERVICE" : "EXAMPLE DATA"}</span>
            <p className="ar-caption" style={{ color: "var(--text-on-dark-muted)", marginTop: 8 }}>
              {live ? settings.api.replace(/^https?:\/\//, "") : "Add the shared secret in Settings to drive real workflows."}
            </p>
          </div>
        </div>
      </aside>
      <nav className="mobile-nav" aria-label="Console">{links}</nav>
      <main className="main">
        <header className="topbar">
          <div>
            <span className="ar-overline muted">{eyebrow}</span>
            <h2>{title}</h2>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            {key === "board" && <Button variant="secondary" size="sm" onClick={() => setRefresh((n) => n + 1)} iconLeft={<Icon name="refresh" size={16} />}>Refresh</Button>}
          </div>
        </header>
        {key === "board" ? (
          <Board live={live} refreshKey={refresh} initial={initial} />
        ) : (
          <div className="panel">
            <SettingsView tab={settingsTab} onTab={(t) => nav(t === "signals" ? "settings/signals" : "settings")}
              onSaved={() => { setRefresh((n) => n + 1); setToast(settings.secret ? "Secret saved for this tab." : "Secret removed. Showing example data."); }} />
          </div>
        )}
      </main>
      {toast && (
        <div style={{ position: "fixed", right: 24, bottom: 24, zIndex: 200 }}>
          <Toast tone="positive" title={toast} onDismiss={() => setToast(null)} />
        </div>
      )}
    </div>
  );
}

function SettingsView({ tab, onTab, onSaved }) {
  return (
    <>
      <Tabs value={tab} onChange={onTab} items={[{ value: "connection", label: "Connection" }, { value: "signals", label: "Signal reference" }]} />
      {tab === "connection" ? <Connection onSaved={onSaved} /> : <SignalCatalog />}
    </>
  );
}
