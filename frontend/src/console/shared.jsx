/* Pieces shared by the console and the platform views. */
import React from "react";
import { Badge, Button, Card, Icon, Verdict } from "../ds";
import { ApiError, api } from "../api";

export const SEV = { ALLOW: 0, WARN: 1, DEFER: 2, KILL: 3 };

export function useAsync(fn, deps) {
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

/* ---------------------------------------------------------------- pieces */
// The signal catalog (code -> plain-language meaning, from angryrobot/catalog.py) is small,
// public and static for a given deploy, so it's fetched once and cached at module scope rather
// than threaded as a prop through every place a Signals chip is rendered.
let catalogCache = null;
let catalogInFlight = null;
function useSignalCatalog() {
  const [cat, setCat] = React.useState(catalogCache);
  React.useEffect(() => {
    if (catalogCache) return;
    catalogInFlight ||= api.signals().then((d) => d.signals || {}).catch(() => ({}));
    catalogInFlight.then((c) => { catalogCache = c; setCat(c); });
  }, []);
  return cat;
}

export function Signals({ list = [] }) {
  const catalog = useSignalCatalog();
  if (!list.length) return null;
  return (
    <div className="chips">
      {list.map((s, i) => {
        const meaning = catalog?.[s.name]?.significa;
        const label = meaning || s.name;
        const tip = meaning ? `${s.name}${s.evidence ? ` — ${s.evidence}` : ""}` : s.evidence;
        return (
          <span key={i} className={`chip ${s.floor ? "floor" : ""}`} title={tip}>
            {label.length > 64 ? `${label.slice(0, 61)}…` : label}
          </span>
        );
      })}
    </div>
  );
}

export function ErrorNote({ error, onRetry }) {
  return (
    <Card ground="sand" eyebrow="SERVICE" padding={20}>
      <p className="ar-small">{error instanceof ApiError ? error.message : String(error)}</p>
      {onRetry && <Button variant="secondary" size="sm" style={{ marginTop: 14 }} onClick={onRetry} iconLeft={<Icon name="refresh" size={16} />}>Try again</Button>}
    </Card>
  );
}

export function DemoBanner({ onConnect }) {
  return (
    <div className="banner" role="note">
      <span className="ar-mono">EXAMPLE DATA</span>
      <span style={{ flex: "1 1 280px" }}>These are the nine rogue-lab runs from 19 Sep. Add the shared secret to see live runs.</span>
      <Button size="sm" variant="secondary" onClick={onConnect}>Connect</Button>
    </div>
  );
}

export function Timeline({ items }) {
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

export function RunDrawer({ run, live, onClose }) {
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

