/* Operator console. Flat and square end to end (kit rule: no glass over data). Hazard Orange marks
   the active nav rule, the "needs a human" count and the one primary action per view. */
import React from "react";
import { Badge, Button, Card, Icon, Input, Logo, Select, Tabs, Toast, Verdict } from "../ds";
import { ApiError, DEFAULT_API, api, settings } from "../api";
import { DEMO_RUNS } from "../demo";

const NAV = [
  ["overview", "Needs a human", "siren"],
  ["runs", "Runs", "activity"],
  ["try", "Audit an action", "flask"],
  ["signals", "Signals", "book-open"],
  ["connection", "Connection", "plug"],
];
const TITLES = { overview: ["01 / Today", "Needs a human"], runs: ["02 / Runs", "Agent runs"],
  try: ["03 / Playground", "Audit an action"], signals: ["04 / Reference", "Signal catalog"], connection: ["05 / Settings", "Connection"] };
const SEV = { ALLOW: 0, WARN: 1, DEFER: 2, KILL: 3 };

function useAsync(fn, deps) {
  const [state, setState] = React.useState({ loading: true, data: null, error: null });
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    fn().then((data) => live && setState({ loading: false, data, error: null }))
      .catch((error) => live && setState({ loading: false, data: null, error }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return [state, () => setTick((t) => t + 1)];
}

/* ---------------------------------------------------------------- data */
function demoAlerts() {
  return DEMO_RUNS.flatMap((r) => r.timeline.filter((e) => e.action && e.verdict !== "ALLOW").map((e) => ({
    ...e, run_id: r.run_id, workflow: r.profile, persona: r.persona, ira_score: e.ira,
  }))).sort((a, b) => SEV[b.verdict] - SEV[a.verdict] || b.ira_score - a.ira_score);
}

function useData(live, refreshKey) {
  const [runs] = useAsync(() => (live ? api.runs(50).then((d) => d.runs) : Promise.resolve(DEMO_RUNS.map(({ timeline, ...r }) => r))), [live, refreshKey]);
  const [alerts] = useAsync(() => (live ? api.alerts(100).then((d) => d.alerts) : Promise.resolve(demoAlerts())), [live, refreshKey]);
  return { runs, alerts };
}

/* ---------------------------------------------------------------- pieces */
function Signals({ list = [] }) {
  if (!list.length) return null;
  return (
    <div className="chips">
      {list.map((s, i) => (
        <span key={i} className={`chip ${s.floor ? "floor" : ""}`} title={s.evidence}>
          <span className="code">{s.name}</span>{s.pw ? <span className="muted num">{s.pw}</span> : null}
        </span>
      ))}
    </div>
  );
}

function ErrorNote({ error, onRetry }) {
  return (
    <Card ground="sand" eyebrow="SERVICE" padding={20}>
      <p className="ar-small">{error instanceof ApiError ? error.message : String(error)}</p>
      {onRetry && <Button variant="secondary" size="sm" style={{ marginTop: 14 }} onClick={onRetry} iconLeft={<Icon name="refresh" size={16} />}>Try again</Button>}
    </Card>
  );
}

function DemoBanner({ onConnect }) {
  return (
    <div className="banner" role="note">
      <span className="ar-mono">EXAMPLE DATA</span>
      <span style={{ flex: "1 1 280px" }}>These are the nine rogue-lab runs from 19 Sep. Add the shared secret to see live runs.</span>
      <Button size="sm" variant="secondary" onClick={onConnect}>Connect</Button>
    </div>
  );
}

function Timeline({ items }) {
  return (
    <div className="tl">
      {items.map((e, i) => {
        if (e.phase === "input") {
          return (
            <div key={i} className="tl-item">
              <span className={`tl-bar ${e.signals?.length ? "WARN" : ""}`} />
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span className="ar-mono muted">INPUT · {e.kind === "tool_result" ? "TOOL RESULT" : "CALLER"} {e.at ? `· ${e.at}` : ""}</span>
                <span className="ar-small">{e.content}</span>
                <Signals list={e.signals} />
              </div>
            </div>
          );
        }
        if (e.phase === "reply") {
          return (
            <div key={i} className="tl-item">
              <span className="tl-bar" />
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span className="ar-mono muted">SENT TO CALLER</span>
                <span className="ar-small">{e.content || <span className="muted">(no text)</span>}</span>
                {e.tool_calls?.length ? <span className="code muted">{e.tool_calls.join(", ")}</span> : null}
              </div>
            </div>
          );
        }
        const a = e.action || {};
        return (
          <div key={i} className="tl-item">
            <span className={`tl-bar ${e.verdict}`} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <Verdict v={e.verdict} />
                <span className="ar-mono num">IRA {Number(e.ira ?? e.ira_score ?? 0).toFixed(1)}</span>
                <span className="ar-mono muted">{e.phase === "resample" ? "RESAMPLE · " : ""}{a.tool === "say" ? "SENTENCE" : `TOOL ${a.tool}`}</span>
              </div>
              {a.tool === "say"
                ? <span className="ar-small">“{a.text}”</span>
                : <span className="code ar-small" style={{ wordBreak: "break-word" }}>{a.tool}({JSON.stringify(a.args)})</span>}
              {e.verdict !== "ALLOW" && <span className="ar-small muted">{e.explanation}</span>}
              <Signals list={e.signals} />
              {e.reasoning_excerpt ? (
                <details>
                  <summary className="ar-caption muted" style={{ cursor: "pointer" }}>Agent reasoning · {e.reasoning_source}</summary>
                  <p className="ar-caption" style={{ marginTop: 6, color: "var(--text-body)" }}>{e.reasoning_excerpt}</p>
                </details>
              ) : null}
              {e.enforcement && e.enforcement !== "ninguna" && <span className="ar-caption muted">Lever: {e.enforcement}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RunDrawer({ run, live, onClose }) {
  const [detail] = useAsync(() => (live ? api.run(run.run_id) : Promise.resolve(run)), [run.run_id, live]);
  const tl = detail.data?.timeline || [];
  const worst = tl.filter((e) => e.action).sort((a, b) => SEV[b.verdict] - SEV[a.verdict] || (b.ira || 0) - (a.ira || 0))[0];
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside className="drawer" aria-label={`Run ${run.run_id}`}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, padding: "24px 24px 18px", borderBottom: "1px solid var(--border-subtle)" }}>
        <div>
          <span className="ar-mono muted">RUN {run.run_id}</span>
          <h3 className="ar-h5" style={{ marginTop: 8 }}>{run.persona ? `${run.persona} · ${run.why}` : run.profile}</h3>
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            {run.summary?.killed || run.killed ? <Badge tone="accent" dot>Stopped</Badge> : null}
            <Badge>{(run.summary?.actions ?? run.actions) || 0} actions</Badge>
            <Badge tone="info">IRA max {(run.summary?.ira_max ?? run.ira_max ?? 0).toFixed?.(1)}</Badge>
          </div>
        </div>
        <button onClick={onClose} aria-label="Close" className="ar-x">×</button>
      </div>
      <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20, overflow: "auto", flex: 1 }}>
        {detail.error && <ErrorNote error={detail.error} />}
        {worst && worst.verdict !== "ALLOW" && (
          <Card ground="signal" eyebrow="WHY THIS REACHED YOU" padding={20}>
            <p className="ar-small">{worst.explanation}</p>
            {worst.decided_by && <p className="ar-caption" style={{ marginTop: 8 }}>Decided by {worst.decided_by}.</p>}
          </Card>
        )}
        <Card ground="paper" eyebrow="TIMELINE" padding={20}>
          {detail.loading ? <p className="ar-small muted">Loading the run.</p> : <Timeline items={tl} />}
        </Card>
      </div>
    </aside>
  );
}

/* ---------------------------------------------------------------- views */
function Overview({ data, live, onOpenRun }) {
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
          <div className="metric-num num" style={{ color: "var(--ar-orange)" }}>{human.length}</div>
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

function Runs({ data, onOpenRun }) {
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

function TryAction({ live, onConnect }) {
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

function SignalCatalog() {
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

function Connection({ onSaved }) {
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
export default function Console({ view = "overview" }) {
  const [refresh, setRefresh] = React.useState(0);
  const live = Boolean(settings.secret);
  const data = useData(live, refresh);
  const [openRun, setOpenRun] = React.useState(null);
  const [toast, setToast] = React.useState(null);
  const nav = (v) => { window.location.hash = `#/console/${v}`; };
  const humanCount = (data.alerts.data || []).filter((a) => a.verdict === "DEFER" || a.verdict === "KILL").length;
  const runsById = Object.fromEntries((live ? data.runs.data || [] : DEMO_RUNS).map((r) => [r.run_id, r]));
  const open = (id) => setOpenRun(runsById[id] || { run_id: id, profile: "", summary: {} });
  const [eyebrow, title] = TITLES[view] || TITLES.overview;

  React.useEffect(() => { setOpenRun(null); }, [view]);

  React.useEffect(() => {
    if (!live || (view !== "overview" && view !== "runs")) return undefined;
    const t = setInterval(() => setRefresh((n) => n + 1), 8000);
    return () => clearInterval(t);
  }, [live, view]);

  const links = NAV.map(([k, label, icon]) => (
    <button key={k} className={`side-link ${view === k ? "is-on" : ""}`} onClick={() => nav(k)} aria-current={view === k ? "page" : undefined}>
      <Icon name={icon} size={18} />{label}
      {k === "overview" && humanCount > 0 && <span className="ar-mono" style={{ marginLeft: "auto", color: "var(--ar-orange)" }}>{humanCount}</span>}
    </button>
  ));

  return (
    <div className="console">
      <aside className="sidebar">
        <a href="#/" style={{ padding: "0 20px 26px", display: "inline-flex" }} aria-label="AngryRobot home"><Logo variant="lockup" tone="paper" height={20} /></a>
        <nav aria-label="Console">{links}</nav>
        <div style={{ marginTop: "auto", padding: "0 20px" }}>
          <div style={{ boxShadow: "var(--shadow-hairline-dark)", padding: 14 }}>
            <span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>{live ? "LIVE SERVICE" : "EXAMPLE DATA"}</span>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 8 }}>
              <span style={{ fontFamily: "var(--font-display)", fontSize: 32, lineHeight: 1, color: "var(--ar-orange)" }}>{humanCount}</span>
              <span style={{ fontSize: 13, color: "var(--text-on-dark-muted)" }}>need a human</span>
            </div>
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
            {(view === "overview" || view === "runs") && (
              <Button variant="secondary" size="sm" onClick={() => setRefresh((n) => n + 1)} iconLeft={<Icon name="refresh" size={16} />}>Refresh</Button>
            )}
          </div>
        </header>
        <div className="panel">
          {!live && view !== "connection" && view !== "signals" && <DemoBanner onConnect={() => nav("connection")} />}
          {view === "overview" && <Overview data={data} live={live} onOpenRun={open} />}
          {view === "runs" && <Runs data={data} onOpenRun={open} />}
          {view === "try" && <TryAction live={live} onConnect={() => nav("connection")} />}
          {view === "signals" && <SignalCatalog />}
          {view === "connection" && <Connection onSaved={() => { setRefresh((n) => n + 1); setToast(settings.secret ? "Secret saved for this tab." : "Secret removed. Showing example data."); }} />}
        </div>
      </main>
      {openRun && <RunDrawer run={openRun} live={live && !openRun.persona} onClose={() => setOpenRun(null)} />}
      {toast && (
        <div style={{ position: "fixed", right: 24, bottom: 24, zIndex: 200 }}>
          <Toast tone="positive" title={toast} onDismiss={() => setToast(null)} />
        </div>
      )}
    </div>
  );
}
