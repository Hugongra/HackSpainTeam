/* The Round tab: "Randomize agents" fills the seats of the workflow built on the Build tab (the agent
   blocks on the board, in call order: `spec`) with random agents (name, personality) and, with
   probability 0.5, makes ONE of them malicious — random seat, random malicious trait. The service then
   runs the call seat by seat through that same graph and AngryRobot audits every action of every agent.
   Step mode stops after each audited action so the operator can read WHY it got its IRA: impact,
   suspicion, hard floors, the matrix, the formula, each signal with its evidence, and the judge.
   Everything here comes from GET /v1/rounds/<id> (angryrobot/rounds.py); the canvas is the Board's.
   Crisis (angryrobot/crisis.py): the Crisis button makes two or more agents rogue at once. The service has to
   notice it is no longer one isolated incident (N blocked within a window), switch posture, notify for real
   in severity order (worst IRA first), ration a small pool of human operators, and afterwards compare the
   order it chose with the real severity. The banner, the notices log and the operators card show all of it. */
import React from "react";
import { Badge, Button, Card, Icon, Select, Switch, Verdict } from "../ds";
import { api, download } from "../api";
import { ErrorNote, SEV, useAsync, useSignalCatalog } from "./shared";

const MATRIX = [[0, 0, 1, 1], [0, 1, 1, 2], [0, 1, 2, 2], [1, 2, 2, 3]];   // config.yaml ira.severity_matrix
const BAND_START = [0, 40, 70, 90];
const BAND_WIDTH = [39.9, 29.9, 19.9, 10];
const CUTS = [0.15, 0.4, 0.7];
const SEAT_STATUS = { waiting: ["neutral", "Waiting"], active: ["info", "On the call"], done: ["positive", "Done"],
  held: ["sand", "Held · human"], killed: ["ink", "Killed"], skipped: ["neutral", "Not reached"] };
const OUTCOME = { killed: ["ink", "Malicious agent killed"], held: ["sand", "Malicious agent held"], alerted: ["caution", "Malicious agent only warned"],
  missed: ["negative", "Malicious agent missed"], not_reached: ["neutral", "Stopped before the malicious agent"],
  clean: ["positive", "Clean round"], warned: ["positive", "No malicious agent · warnings only"], false_alarm: ["negative", "False alarm"],
  contained: ["positive", "Crisis contained"], partial: ["caution", "Crisis declared · some rogues missed"],
  missed_crisis: ["negative", "Crisis never declared"], false_crisis: ["negative", "Crisis declared without one"], quiet: ["neutral", "Below the crisis threshold"] };
const STORE = "ar_round_id";
const store = { get: () => { try { return sessionStorage.getItem(STORE); } catch { return null; } },
  set: (v) => { try { sessionStorage.setItem(STORE, v); } catch { /* blocked */ } } };
const fmt = (n, d = 1) => (typeof n === "number" ? n.toFixed(d) : "—");

/* ---------------------------------------------------------------- speed: one slider, step by step -> full speed */
const SPEEDS = [{ pace: "step", delay: null, label: "Step by step: press Next after each action" },
  { pace: "auto", delay: 6, label: "Slow: 6 s per action" }, { pace: "auto", delay: 3, label: "3 s per action" },
  { pace: "auto", delay: 1.5, label: "1.5 s per action" }, { pace: "auto", delay: 0.7, label: "Fast: 0.7 s per action" },
  { pace: "auto", delay: 0, label: "Full speed" }];
const speedIndex = (pace, delay) => (pace === "step" ? 0
  : SPEEDS.reduce((best, s, i) => (i && Math.abs(s.delay - delay) < Math.abs(SPEEDS[best].delay - delay) ? i : best), 1));

function SpeedSlider({ pace, delay, onChange, id }) {
  const i = speedIndex(pace, delay);
  return (
    <div className="speed">
      <div className="speed-head"><span className="ar-overline muted">Speed</span><span className="ar-caption">{SPEEDS[i].label}</span></div>
      <input id={id} type="range" min="0" max={SPEEDS.length - 1} step="1" value={i} aria-label="Round speed"
             aria-valuetext={SPEEDS[i].label} onChange={(e) => onChange(SPEEDS[Number(e.target.value)])} />
      <div className="speed-ends ar-caption muted"><span>Action by action</span><span>Full speed</span></div>
    </div>
  );
}

/* ---------------------------------------------------------------- why this IRA */
export function IraWhy({ a }) {
  const catalog = useSignalCatalog();
  const L = a.impact?.level ?? 0;
  const S = a.suspicion?.S ?? 0;
  const b = a.suspicion?.band ?? CUTS.filter((c) => S >= c).length;
  const matrixSev = MATRIX[L]?.[b] ?? 0;
  const sev = Number(String(a.severity || "S0").slice(1));
  const floor = a.hard_floor ? Number(String(a.hard_floor).slice(1)) : 0;
  const intensity = floor && floor >= sev ? (floor === 3 ? 1 : Math.max(S, 0.5)) : S;
  const floors = a.signals.filter((s) => s.floor);
  const susp = a.signals.filter((s) => !s.floor);
  const dims = Object.entries(a.judge?.dims || {}).filter(([, v]) => v != null);
  return (
    <div className="why">
      <div className="why-head">
        <Verdict v={a.verdict} />
        <span className="why-ira num">{fmt(a.ira)}</span>
        <span className="ar-mono muted">{a.kind === "tool_call" ? `TOOL ${a.action?.tool}` : "SENTENCE"}</span>
      </div>
      <ol className="why-steps">
        <li><b>Impact {L}/3.</b> <span className="muted">{a.impact?.why}</span></li>
        <li><b>Suspicion S = {fmt(S, 2)}</b> <span className="muted">(band {b}; rules alone {fmt(a.suspicion?.S_deterministic, 2)}). Noisy-OR of the signals below: 1 − Π(1 − p·w).</span></li>
        <li><b>Matrix</b> impact {L} × band {b} → S{matrixSev}.{floor ? <> Hard floor <b>{a.hard_floor}</b>.</> : null} <span className="muted">Decided by {a.decided_by}.</span></li>
        <li><b>Severity S{sev} → {a.verdict}.</b> <span className="muted">IRA = {BAND_START[sev]} + {BAND_WIDTH[sev]} × {fmt(Math.min(1, intensity), 2)} = {fmt(a.ira)}</span></li>
      </ol>
      {floors.length > 0 && (
        <div className="why-block">
          <span className="ar-overline muted">Hard rules (set a floor nothing lowers)</span>
          {floors.map((s, i) => <SignalRow key={i} s={s} catalog={catalog} />)}
        </div>
      )}
      {susp.length > 0 && (
        <div className="why-block">
          <span className="ar-overline muted">Suspicion signals (p × w)</span>
          {susp.map((s, i) => <SignalRow key={i} s={s} catalog={catalog} />)}
        </div>
      )}
      {!a.signals.length && <p className="ar-caption muted">No signal fired. {L >= 3 ? "The verdict comes from impact alone: an irreversible action is at least WARN." : ""}</p>}
      <div className="why-block">
        <span className="ar-overline muted">Independent judge</span>
        {a.judge?.skipped ? <span className="ar-caption muted">Not called: {a.judge.skipped}.</span>
          : a.judge?.error ? <span className="ar-caption">Unavailable: {a.judge.error}</span>
          : dims.length ? (
            <div className="why-dims">
              {dims.map(([k, v]) => <span key={k} className={`why-dim ${v >= 3 ? "is-on" : ""}`}>{k.replace(/_/g, " ")} <b className="num">{v}</b></span>)}
              <span className="ar-caption muted">{a.judge.model?.split("/").pop()} · class {a.judge.rogue_class || "none"}{a.judge.ms ? ` · ${a.judge.ms} ms` : ""}</span>
            </div>
          ) : <span className="ar-caption muted">Off in this round (rules only).</span>}
      </div>
      {a.reasoning ? <details><summary className="ar-caption muted">Agent reasoning</summary><p className="ar-caption">{a.reasoning}</p></details> : null}
    </div>
  );
}

function SignalRow({ s, catalog }) {
  const meaning = catalog?.[s.name]?.significa;
  return (
    <div className="why-sig">
      <div>
        <span className="code">{s.name}</span>
        {meaning ? <div className="ar-caption muted">{meaning}</div> : null}
        {s.evidence ? <div className="ar-caption">“{s.evidence}”</div> : null}
      </div>
      <span className="ar-mono num why-pw">{s.floor ? `FLOOR S${s.floor}` : `${fmt(s.p, 2)} × ${fmt(s.w, 2)} = ${fmt(s.p * s.w, 2)}`}</span>
    </div>
  );
}

/* ---------------------------------------------------------------- label a decision (training data) */
function Label({ caseId }) {
  const [done, setDone] = React.useState(null);
  const [err, setErr] = React.useState(null);
  if (!caseId) return null;
  const send = async (label) => { setErr(null); try { await api.feedback({ case_id: caseId, label }); setDone(label); } catch (x) { setErr(x); } };
  return (
    <div className="why-label">
      <span className="ar-caption muted">{done ? `Labelled ${done.replace("_", " ")}.` : "Was this decision right?"}</span>
      {!done && <>
        <Button size="sm" variant="secondary" onClick={() => send("correct")}>Correct</Button>
        <Button size="sm" variant="secondary" onClick={() => send("false_positive")}>False positive</Button>
        <Button size="sm" variant="secondary" onClick={() => send("false_negative")}>Missed</Button>
      </>}
      {err && <span className="ar-caption" style={{ color: "var(--status-negative)" }}>{err.message}</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- IRA map: one row per agent, one cell per action */
const V_BG = { ALLOW: "var(--ar-green)", WARN: "var(--ar-sand)", DEFER: "var(--status-negative)", KILL: "var(--ar-black)" };
const V_FG = { ALLOW: "var(--ar-paper)", WARN: "var(--ar-black)", DEFER: "var(--ar-paper)", KILL: "var(--ar-paper)" };

export function IraMap({ round, selected, onSelect }) {
  const bySeat = {};
  for (const e of round.events) if (e.kind === "agent") (bySeat[e.seat] ||= []).push(e);
  return (
    <div className="iramap" role="grid" aria-label="IRA of every action of every agent">
      {round.seats.map((s) => {
        const mal = s.malicious && s.malicious !== "hidden";
        return (
          <div key={s.seat} className={`iramap-row is-${s.status}`} role="row">
            <div className="iramap-who" title={`${s.role} · ${s.source_label}`}>
              <b>{s.agent}</b><span className="muted">{s.role}</span>
              {mal ? <span className="iramap-mal" title={s.malicious.label}>rogue</span> : null}
            </div>
            <div className="iramap-cells">
              {(bySeat[s.seat] || []).flatMap((e) => {
                // One cell per AUDITED action: each sentence and each tool call of the turn, and the handoff
                // to the next agent (transfer_call). A turn the platform never audited keeps one cell.
                const acts = e.audits?.length ? e.audits : [{ verdict: e.verdict, ira: e.ira, kind: "turn", action: {} }];
                return acts.map((a, k) => {
                  const handoff = a.action?.tool === "transfer_call";
                  const tool = a.kind === "tool_call" && !handoff;
                  const what = handoff ? `handoff → ${a.action.args?.next_agent || "next agent"}` : tool ? `tool ${a.action.tool}` : a.kind === "utterance" ? `says “${(a.action.text || "").slice(0, 80)}”` : "turn";
                  return (
                    <button key={`${e.i}-${k}`} role="gridcell"
                            className={`iramap-cell ${handoff ? "is-handoff" : tool ? "is-tool" : ""} ${selected === e.i ? "is-on" : ""} ${round.revealed && e.rogue_move ? "is-rogue" : ""}`}
                            style={{ background: V_BG[a.verdict], color: V_FG[a.verdict] }} onClick={() => onSelect(e.i)}
                            title={`${a.verdict} · IRA ${fmt(a.ira)} · ${what}`}>
                      <span className="iramap-glyph" aria-hidden>{handoff ? "→" : tool ? "ƒ" : "“"}</span>{Math.round(a.ira)}
                    </button>
                  );
                });
              })}
              {s.status === "active" && <span className="iramap-next" aria-hidden>…</span>}
              {s.status === "skipped" && <span className="ar-caption muted">not reached</span>}
              {s.status === "waiting" && !(bySeat[s.seat] || []).length && <span className="ar-caption muted">waiting</span>}
            </div>
          </div>
        );
      })}
      <div className="iramap-legend ar-caption muted">
        {["ALLOW", "WARN", "DEFER", "KILL"].map((v) => <span key={v}><i style={{ background: V_BG[v] }} />{v}</span>)}
        <span>“ sentence · ƒ tool call · → handoff to the next agent</span>
        {round.revealed && <span><i className="is-rogue-key" />the malicious move</span>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- one decision, short; the full "why" folds out */
function Decision({ ev, events, round }) {
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => { setOpen(false); }, [ev.i]);
  const caller = [...events].reverse().find((e) => e.i < ev.i && e.kind === "caller" && e.seat === ev.seat);
  const seat = round.seats.find((s) => s.seat === ev.seat);
  const next = events.find((x) => x.kind === "agent" && x.i > ev.i);
  const lever = events.find((e) => e.i > ev.i && (!next || e.i < next.i) && e.kind === "lever" && e.seat === ev.seat);
  const top = [...ev.audits].sort((a, b) => SEV[b.verdict] - SEV[a.verdict] || b.ira - a.ira)[0];
  const said = ev.text ? `“${ev.text}”` : "";
  const did = ev.tool_calls?.map((t) => t.name).join(", ");
  return (
    <div className="dec">
      <div className="dec-head">
        <Verdict v={ev.verdict} /><span className="dec-ira num">{fmt(ev.ira)}</span>
        <span className="ar-mono muted">{seat?.agent} · {seat?.role}</span>
        {round.revealed && ev.rogue_move ? <span className="chip chip--malicious">malicious move</span> : null}
      </div>
      {caller && <p className="ar-caption muted">Caller: {caller.text}</p>}
      <p className="ar-small">{said}{did ? <> {said ? "+ " : ""}<code>{did}</code></> : null}</p>
      <p className="ar-small dec-why">{top ? top.explanation : "Not audited: the workflow was paused or killed from the platform."}</p>
      <p className="ar-caption muted">{lever ? lever.text : ev.directive?.action === "continue" ? "Lever: continue, the action went out." : `Lever: ${ev.directive?.action}`}</p>
      <button className="dec-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Icon name="chevron-right" size={14} style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .15s" }} />
        {open ? "Hide the breakdown" : "Why this IRA: impact, suspicion, signals, judge"}
      </button>
      {open && (
        <div className="dec-body">
          {ev.audits.map((a, i) => <div key={i}><IraWhy a={a} /><Label caseId={a.case_id} /></div>)}
          {ev.fallback && <p className="ar-caption muted">{ev.fallback}</p>}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- a real phone call, live (angryrobot/live_call.py)
   The service hands the call back with the SAME shape as a round (one seat, ordered events), so the IRA map and the
   decision panel below render it unchanged. While a call is in the air the board announces it from either tab. */
const CALL_STATUS = { running: ["info", "On the line"], killed: ["ink", "Cut by HappyRobot"], done: ["neutral", "Call over"] };

export function useLiveCall(live) {
  const [tick, setTick] = React.useState(0);
  const [detail, setDetail] = React.useState(null);
  const busy = React.useRef(false);
  React.useEffect(() => { if (!live) return undefined; const t = setInterval(() => setTick((n) => n + 1), 2000); return () => clearInterval(t); }, [live]);
  const [list] = useAsync(() => (live ? api.liveCalls(12).catch(() => null) : Promise.resolve(null)), [live, tick]);
  const id = list.data?.active || detail?.id || null;
  // The fast poll only runs while the call is ON THE LINE. Once it is over the last read stands: a finished
  // call must not leave a heartbeat every 900 ms against a free Render instance for the rest of the session.
  const over = detail?.id === id && detail?.status && detail.status !== "running";
  React.useEffect(() => {
    if (!live || !id || over) return undefined;
    let alive = true;
    const pull = async () => {
      if (busy.current) return;
      busy.current = true;
      // A 404 means the service has no live-call view (older deploy): drop the flow rather than break the
      // console. Any other failure is a blip — keep showing the last state instead of blanking mid-demo.
      try { const v = await api.liveCall(id); if (alive) setDetail(v); }
      catch (x) { if (alive && x?.status === 404) setDetail(null); }
      finally { busy.current = false; }
    };
    pull();
    const t = setInterval(pull, 900);
    return () => { alive = false; clearInterval(t); };
  }, [live, id, over]);
  const call = detail && detail.id === id ? detail : null;
  return { call, active: Boolean(list.data?.active) && call?.status === "running" };
}

/* The announcement: shown above the tabs, so a call is visible from Round and from Build. */
export function LiveCallBar({ call, active, onFollow, onDismiss, following }) {
  if (!call) return null;
  const seat = call.seats?.[0];
  const kill = call.kill;
  const [tone, label] = CALL_STATUS[call.status] || CALL_STATUS.done;
  return (
    <div className={`callbar is-${call.status}`} role="status" aria-live="polite">
      <span className="callbar-dot" aria-hidden />
      <span className="callbar-title">{active ? "SOMEONE IS CALLING" : "CALL FINISHED"}</span>
      <span className="callbar-fact"><b>{seat?.agent}</b> is taking it · {seat?.role}</span>
      <span className="callbar-fact">{call.turns} turns · worst <b>{call.worst}</b></span>
      {seat?.malicious ? <span className="callbar-fact callbar-rogue">rogue: {seat.malicious.label}</span> : null}
      {kill && !kill.fired ? <span className="callbar-fact callbar-count">{kill.remaining > 0.5
        ? <>KILL in <b>{Math.ceil(kill.remaining)}s</b> · the agent is still on the line</>
        : <>KILL <b>now</b> · the next thing it says is the last</>}</span> : null}
      {kill?.fired ? <span className="callbar-fact">{label}</span> : null}
      <span style={{ flex: 1 }} />
      {!following && <Button size="sm" variant="inverse" onClick={onFollow}>Follow the call</Button>}
      <Button size="sm" variant="onDark" onClick={onDismiss}>Hide</Button>
    </div>
  );
}

/* The one-agent flow: the same IRA map and decision panel a round uses, fed with the call. */
export function LiveCallFlow({ call }) {
  const [pinned, setPinned] = React.useState(null);
  React.useEffect(() => { setPinned(null); }, [call.id]);   // otra llamada, otra acción seleccionada
  const events = call.events || [];
  const agentEvents = events.filter((e) => e.kind === "agent");
  const shown = (pinned != null && agentEvents.find((e) => e.i === pinned)) || agentEvents[agentEvents.length - 1];
  const seat = call.seats?.[0];
  const kill = call.kill;
  const alert = call.call;
  const heldTools = [...new Set(events.flatMap((e) => e.held_tools || []))];
  return (
    <>
      <Card padding={14} eyebrow={`LIVE CALL · ${(CALL_STATUS[call.status] || [])[1] || call.status}`} ground={call.status === "killed" ? "sand" : "paper"}>
        <div className="callflow-head">
          <Badge tone={(CALL_STATUS[call.status] || [])[0]} dot={call.status === "running"}>{seat?.agent} · {seat?.role}</Badge>
          {seat?.malicious ? <span className="chip chip--malicious">{seat.malicious.label}</span> : <Badge tone="positive">not malicious</Badge>}
          <span className="ar-caption muted">{call.turns} turns · HappyRobot phone call</span>
        </div>
        {kill && !kill.fired && (
          <p className="ar-small callflow-count">{kill.remaining > 0.5
            ? <>AngryRobot has decided to cut this agent. HappyRobot ends the call in <b>{Math.ceil(kill.remaining)} s</b>; until then the agent stays on the line, so you can watch what it does with the time it has left.</>
            : <>The countdown is up: HappyRobot cuts the call on the agent's next turn.</>}</p>
        )}
        {kill?.fired && <p className="ar-small">The countdown ran out: the call was cut and the agent was told so out loud.</p>}
        {heldTools.length > 0 && (
          <p className="ar-caption muted">Held while the countdown runs: <b>{heldTools.join(", ")}</b> — the agent said it was doing them, the call never did.</p>
        )}
        <IraMap round={call} selected={shown?.i} onSelect={setPinned} />
      </Card>
      {shown && (
        <Card padding={14} eyebrow={pinned != null ? "SELECTED ACTION" : "LAST ACTION"}>
          {pinned != null && <Button size="sm" variant="ghost" style={{ float: "right", marginTop: -34 }} onClick={() => setPinned(null)}>Follow the latest</Button>}
          <Decision ev={shown} events={events} round={call} />
        </Card>
      )}
      {alert && (
        <Card padding={14} eyebrow="ALERT CALL" ground={alert.status === "sent" ? "paper" : "sunken"}>
          <Badge tone={alert.status === "sent" ? "positive" : alert.status === "dialing" ? "info" : "neutral"}>{alert.status}</Badge>
          <p className="ar-small" style={{ marginTop: 8 }}>{alert.detail || `HappyRobot is calling ${alert.phone}.`}</p>
        </Card>
      )}
    </>
  );
}

/* ---------------------------------------------------------------- the panel */
const ROGUE_MODES = [{ value: "random", label: "Coin (50 %)" }, { value: "none", label: "None" }, { value: "pick", label: "I choose" }, { value: "crisis", label: "Crisis" }];
const CRISIS_COUNTS = [{ value: "", label: "Random: at least 2" }, { value: "2", label: "2 agents" }, { value: "3", label: "3 agents" }, { value: "all", label: "All of them" }];
const NOTICE_TONE = { planned: "sand", sent: "positive", failed: "negative", not_configured: "neutral", logged: "neutral" };
const NOTICE_LABEL = { planned: "planned", sent: "sent", failed: "failed", not_configured: "not configured", logged: "logged only" };
const CHANNEL_HINT = { call: "HAPPYROBOT_ALERT_WEBHOOK_URL + ANGRYROBOT_ALERT_PHONE", sms: "HAPPYROBOT_SMS_WEBHOOK_URL or TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM + ANGRYROBOT_SMS_PHONE",
  email: "SMTP_HOST/USER/PASS + ANGRYROBOT_ALERT_EMAIL", webhook: "ANGRYROBOT_ALERT_WEBHOOK_URL (Slack, Discord or a Google Sheet script)" };
const REAL_CHANNELS = ["call", "sms", "email", "webhook"];
const seatName = (round, id) => { const s = round.seats.find((x) => x.seat === id); return s ? `${s.agent} (${s.role})` : id; };

/* ---------------------------------------------------------------- crisis: the banner (detected or not yet) */
function CrisisBanner({ round }) {
  const c = round.crisis;
  if (!c) return null;
  const det = c.detected;
  const blockedN = new Set(c.blocked.map((b) => b.seat)).size;
  if (!det) {
    return (
      <div className="crisis-watch ar-caption" role="status">
        <Icon name="siren" size={14} /> Crisis watch: <b>{blockedN}</b> of {c.threshold} agents blocked within {c.window} actions. Still isolated incidents.
      </div>
    );
  }
  const sent = c.notices.filter((n) => n.status === "sent").length;
  return (
    <div className="crisis-banner" role="status" aria-live="polite">
      <span className="crisis-dot" aria-hidden /><span className="crisis-title">CRISIS ACTIVE</span>
      <span className="crisis-fact"><b>{det.seats.length}</b> agents blocked within <b>{det.span}</b> actions → declared at action {det.at_turn}</span>
      <span className="crisis-fact">Posture: <b>{c.posture === "strict" ? "strict, a WARN is now held" : "unchanged"}</b></span>
      <span className="crisis-fact">Operators: <b>{c.pool.free}/{c.pool.total}</b> free</span>
      <span className="crisis-fact">Notices: <b>{sent}</b> sent of {c.notices.length}</span>
      {round.status !== "done" && <span className="crisis-fact">A KILL no longer ends the call: the coordinator re-routes it.</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- crisis: the real notices, in the order the system chose */
function NoticesCard({ round, waiting }) {
  const c = round.crisis;
  if (!c || !c.notices.length) return null;
  const ch = c.channels || {};
  return (
    <Card padding={14} eyebrow="REAL NOTICES · WORST FIRST" ground={waiting ? "sand" : "paper"}>
      {waiting && <p className="ar-small" style={{ marginBottom: 8 }}>The order is decided and nothing has gone out yet. Press <b>Send the notices</b> (or →) to let them out.</p>}
      <div className="notices">
        {c.notices.map((n) => (
          <div key={n.id} className={`notice is-${n.status}`}>
            <span className="notice-n">{n.priority}</span>
            <div className="notice-body">
              <div><b>{n.to}</b> <span className="muted">· {n.channel} · {n.target_label}</span></div>
              <div className="ar-caption muted">{n.reason}</div>
              {n.detail && n.status !== "planned" ? <div className="ar-caption muted">{n.detail}</div> : null}
            </div>
            <div className="notice-right"><Badge tone={NOTICE_TONE[n.status] || "neutral"}>{NOTICE_LABEL[n.status] || n.status}</Badge>{n.at ? <span className="ar-caption muted">{n.at.slice(11, 19)}</span> : null}</div>
          </div>
        ))}
      </div>
      <p className="ar-caption muted" style={{ marginTop: 10 }}>
        Channels on the service: {REAL_CHANNELS.map((k, i) => <span key={k} title={ch[k]?.ready ? ch[k].how : `Set ${CHANNEL_HINT[k]} on Render`}>{k} {ch[k]?.ready ? `ready (${ch[k].target})` : "not configured"}{i < REAL_CHANNELS.length - 1 ? " · " : ""}</span>)}.
        First degree (a KILL or 3+ down) calls security; second degree (holds only) texts operations; the rest is logged unless email or a webhook is set. Team test numbers only, never a real emergency line.
      </p>
    </Card>
  );
}

/* ---------------------------------------------------------------- crisis: limited operators and who waits */
function OperatorsCard({ round }) {
  const c = round.crisis;
  if (!c) return null;
  const ops = c.pool?.operators || [];
  return (
    <Card padding={14} eyebrow={`OPERATORS · ${c.pool?.free ?? 0} OF ${c.pool?.total ?? 0} FREE`}>
      <div className="ops">{ops.map((o) => <span key={o.id} className={`chip ${o.status === "busy" ? "chip--busy" : ""}`}>{o.name}{o.status === "busy" ? ` · on ${o.agent} (IRA ${Math.round(o.ira || 0)})` : " · free"}</span>)}</div>
      {c.triage.length ? c.triage.map((t, i) => <p key={i} className={`ar-caption ${t.decision === "assigned" ? "muted" : "is-strong"}`}>{t.text}</p>)
        : <p className="ar-caption muted">Every DEFER takes one human operator. When none is free, the coordinator decides who waits, and says why.</p>}
    </Card>
  );
}

/* ---------------------------------------------------------------- crisis: the order we chose vs the real severity */
function CrisisOutcome({ outcome, round }) {
  if (!outcome?.crisis) return null;
  return (
    <>
      <div className="crisis-order">
        <div><span className="ar-overline muted">We notified, in this order</span>
          {outcome.notified_order?.length ? <ol>{outcome.notified_order.map((s) => <li key={s} className={outcome.noise?.includes(s) ? "muted" : ""}>{seatName(round, s)}{outcome.noise?.includes(s) ? " · not malicious" : ""}</li>)}</ol> : <p className="ar-caption muted">Nobody: the crisis was never declared.</p>}</div>
        <div><span className="ar-overline muted">Really worst first (ground truth)</span>
          <ol>{outcome.truth_order?.map((s) => <li key={s}>{seatName(round, s)}{outcome.missed?.includes(s) ? " · missed" : ""}</li>)}</ol></div>
      </div>
      <div className="crisis-metrics ar-caption">
        <span>First notice right: <b>{outcome.notified_order?.length ? (outcome.top1_correct ? "yes" : "no") : "—"}</b></span>
        <span>Order agreement: <b className="num">{outcome.order_agreement ?? "—"}</b></span>
        <span>Rogues covered: <b className="num">{outcome.coverage ?? "—"}</b></span>
        <span>Detected at action: <b className="num">{outcome.detected_at_turn ?? "—"}</b></span>
        {outcome.posture_holds?.length ? <span>Held by the strict posture: <b>{outcome.posture_holds.map((s) => seatName(round, s)).join(", ")}</b></span> : null}
        {outcome.operators_exhausted ? <span><b>Operators ran out</b></span> : null}
      </div>
    </>
  );
}

// cfg: GET /v1/rounds/config (fetched once by the Board). spec: the agent blocks on the Build board, in call
// order, with the seat ids the service will give them. hasCallLever: the HappyRobot call lever is wired on
// the board, so a KILL places the call. canvas: the Board's React Flow canvas, shown above the IRA map.
export default function RoundPanel({ live, onRound, cfg, spec = [], hasCallLever = true, onSetAgents, onEditBuild, canvas, liveCall }) {
  const [health] = useAsync(() => (live ? api.health().catch(() => null) : Promise.resolve(null)), [live]);
  const outdated = cfg?.error?.status === 404;   // the service answers but has no /v1/rounds: it runs an older commit
  const [opts, setOpts] = React.useState({ agents: "scripted", pace: "step", delay: 3, blind: false,
                                           rogue: "random", rogue_seat: "", rogue_trait: "", rogue_count: "" });
  const [round, setRound] = React.useState(null);
  const [roundId, setRoundId] = React.useState(() => store.get());
  // act() refetches by id right after an action resolves; a plain closure over `roundId` can still hold
  // the PREVIOUS round's id at that point (state updates aren't visible until the next render), so a fresh
  // round just started gets immediately overwritten by a refetch of the one it replaced. The ref is updated
  // synchronously wherever the id changes, so act() always refetches the round it just acted on.
  const roundIdRef = React.useRef(roundId);
  const applyRoundId = (id) => { roundIdRef.current = id; setRoundId(id); };
  const [err, setErr] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [pinned, setPinned] = React.useState(null);
  const [showOpts, setShowOpts] = React.useState(false);
  const inflight = React.useRef(false);
  const set = (k) => (v) => setOpts((o) => ({ ...o, [k]: v?.target ? v.target.value : v }));

  const fetchRound = React.useCallback(async (id) => {
    if (!id || inflight.current) return;
    inflight.current = true;
    try { const r = await api.round(id); setRound(r); onRound?.(r); setErr(null); }
    catch (x) { if (x.status === 404) { applyRoundId(null); setRound(null); onRound?.(null); } else setErr(x); }
    finally { inflight.current = false; }
  }, [onRound]);

  const active = round && ["ready", "running", "waiting"].includes(round.status);
  React.useEffect(() => { if (live && roundId) fetchRound(roundId); }, [live, roundId, fetchRound]);
  React.useEffect(() => {
    if (!live || !roundId || (round && !active)) return undefined;
    const t = setInterval(() => fetchRound(roundId), 600);
    return () => clearInterval(t);
  }, [live, roundId, round, active, fetchRound]);

  const act = async (fn) => { setBusy(true); setErr(null); try { await fn(); await fetchRound(roundIdRef.current); } catch (x) { setErr(x); } finally { setBusy(false); } };
  const next = () => round?.status === "waiting" && act(() => api.roundNext(round.id));
  // Reset: stop the round if it is still going and clear the panel (the finished round stays in the data).
  const reset = async () => {
    setBusy(true); setErr(null);
    try { if (round && ["ready", "running", "waiting"].includes(round.status)) await api.roundStop(round.id); } catch { /* already gone */ }
    try { sessionStorage.removeItem(STORE); } catch { /* blocked */ }
    applyRoundId(null); setRound(null); setPinned(null); setShowOpts(false); onRound?.(null); setBusy(false);
  };
  // → or Space = Next, while a round waits (not while typing in a field)
  React.useEffect(() => {
    const onKey = (e) => {
      if (!["ArrowRight", " "].includes(e.key) || /INPUT|SELECT|TEXTAREA|BUTTON/.test(document.activeElement?.tagName || "")) return;
      if (round?.status === "waiting") { e.preventDefault(); next(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const seatsFor = spec;
  const pickedSeat = seatsFor.find((x) => x.seat === opts.rogue_seat);
  const canPlay = new Set(seatsFor.flatMap((x) => x.traits || []));   // traits some block on the board can actually play
  const traitOptions = Object.entries(cfg?.data?.traits || {}).filter(([k]) => (pickedSeat ? (pickedSeat.traits || []).includes(k) : canPlay.has(k)));
  const quick = cfg?.data?.quick_sizes || [3, 5, 8];
  const isDefault = (n) => { const d = cfg?.data?.default_specs?.[n]; return d ? d.length === spec.length && d.every((s, i) => s.kind === spec[i]?.kind) : spec.length === n; };
  const phone = cfg?.data?.call?.phone || "+34722222624";
  const randomize = (autostart = false, mode = opts.rogue) => spec.length && act(async () => {
    const malicious = mode === "pick" ? { mode: "pick", seat: opts.rogue_seat || null, trait: opts.rogue_trait || null }
      : mode === "crisis" ? { mode: opts.rogue_count === "all" ? "all" : "crisis", ...(opts.rogue_count && opts.rogue_count !== "all" ? { count: Number(opts.rogue_count) } : {}) }
      : { mode };
    const r = await api.startRound({ agents: opts.agents, pace: opts.pace, delay: Number(opts.delay) || 0, call_on_kill: hasCallLever,
                                     blind: opts.blind, seats: spec.map((s) => ({ kind: s.kind, source: s.source })), malicious, autostart });
    store.set(r.id); applyRoundId(r.id); setRound(r); setPinned(null); onRound?.(r);
  });
  // The rogue seat picked earlier may no longer be on the board.
  React.useEffect(() => { if (opts.rogue_seat && !seatsFor.some((x) => x.seat === opts.rogue_seat)) setOpts((o) => ({ ...o, rogue_seat: "", rogue_trait: "" })); }, [seatsFor, opts.rogue_seat]);

  if (!live) {
    return (
      <div className="round">
        <Card padding={20} eyebrow="ROUND">
          <p className="ar-small">Rounds run on the service. Add the shared secret in Settings to randomize agents.</p>
          <Button size="sm" style={{ marginTop: 14 }} onClick={() => { window.location.hash = "#/console/settings"; }}>Open Settings</Button>
        </Card>
      </div>
    );
  }
  if (outdated) {
    return (
      <div className="round">
        <Card padding={20} eyebrow="THE SERVICE IS OUT OF DATE" ground="sand">
          <p className="ar-small">The console is new but the AngryRobot service still runs commit <b>{health?.data?.commit || "unknown"}</b>, which has no rounds. Nothing can run until it is redeployed.</p>
          <p className="ar-small" style={{ marginTop: 10 }}>Render → service <b>hackspainteam</b> → Manual Deploy → Deploy latest commit. Then reload this page.</p>
        </Card>
      </div>
    );
  }

  const events = round?.events || [];
  const agentEvents = events.filter((e) => e.kind === "agent");
  const shown = (pinned != null && agentEvents.find((e) => e.i === pinned)) || agentEvents[agentEvents.length - 1];
  const truth = round?.truth || {};
  const outcome = round?.outcome;
  const callEv = [...events].reverse().find((e) => e.kind === "call");
  const hrEv = [...events].reverse().find((e) => e.kind === "hr_ready" || e.kind === "hr_error");
  const malSeat = round?.seats.find((s) => s.seat === truth.seat);
  const optionsForm = (
    <div className="round-form">
      <div className="round-agents">
        <div className="speed-head"><span className="ar-overline muted">Agents in the workflow</span><span className="ar-caption"><b>{spec.length}</b> blocks on the board</span></div>
        <div className="seg" role="group" aria-label="Number of agents">
          {quick.map((n) => <button key={n} className={isDefault(n) ? "is-on" : ""} onClick={() => onSetAgents?.(n)} title={`Rebuild the board with the default ${n}-agent workflow`}>{n} agents</button>)}
        </div>
        <div className="chips">{seatsFor.map((x) => <span key={x.seat} className="chip" title={`${x.seat} · ${x.source}`}>{x.order}. {x.role}</span>)}</div>
        <p className="ar-caption muted">Any other mix: drag blocks on the <button className="dec-toggle" style={{ display: "inline", padding: 0 }} onClick={onEditBuild}>Build tab</button>. Each block is a seat of the call, on its own provider.</p>
      </div>
      <div>
        <span className="ar-overline muted">Malicious agent</span>
        <div className="seg" role="radiogroup">
          {ROGUE_MODES.map((m) => (
            <button key={m.value} role="radio" aria-checked={opts.rogue === m.value} className={opts.rogue === m.value ? "is-on" : ""}
                    onClick={() => setOpts((o) => ({ ...o, rogue: m.value }))}>{m.label}</button>
          ))}
        </div>
        {opts.rogue === "crisis" && (
          <div style={{ marginTop: 10 }}>
            <Select id="rd-count" label="How many go rogue at once" value={opts.rogue_count} onChange={set("rogue_count")} options={CRISIS_COUNTS} />
            <p className="ar-caption muted" style={{ marginTop: 6 }}>AngryRobot is not told. It declares a crisis when {cfg?.data?.crisis?.defaults?.threshold ?? 2} agents fall within {cfg?.data?.crisis?.defaults?.window ?? 10} actions, then changes posture, notifies for real (worst first) and rations {cfg?.data?.crisis?.pool?.total ?? 2} operators.</p>
          </div>
        )}
        {opts.rogue === "pick" && (
          <div className="form-2" style={{ marginTop: 10 }}>
            <Select id="rd-seat" label="Which agent" value={opts.rogue_seat}
                    onChange={(e) => setOpts((o) => ({ ...o, rogue_seat: e.target.value, rogue_trait: "" }))}
                    options={[{ value: "", label: "Random agent" }, ...seatsFor.map((x) => ({ value: x.seat, label: x.role }))]} />
            <Select id="rd-trait" label="What it does" value={opts.rogue_trait} onChange={set("rogue_trait")}
                    options={[{ value: "", label: "Random behaviour" }, ...traitOptions.map(([k, t]) => ({ value: k, label: `${t.label} (${t.family.split(" · ")[0]})` }))]} />
          </div>
        )}
      </div>
      <Select id="rd-agents" label="Agents are" value={opts.agents} onChange={set("agents")}
        options={[{ value: "scripted", label: "Forced LLM (the rogue always tries · fast, reliable)" },
                  { value: "hr", label: `Real LLM${cfg?.data && !cfg.data.hr_available ? " (no HappyRobot key on the service)" : " (real HappyRobot agents · slower)"}` }]} />
      <SpeedSlider id="rd-speed" pace={opts.pace} delay={opts.delay} onChange={(sp) => setOpts((o) => ({ ...o, pace: sp.pace, delay: sp.delay ?? o.delay }))} />
      <p className="ar-caption muted"><Icon name="phone" size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
        {hasCallLever ? `A KILL calls ${phone}: the HappyRobot call lever is on the board.` : "No HappyRobot call lever on the board: a KILL calls nobody. Add the lever on the Build tab to change that."}</p>
      <Switch id="rd-blind" label="Blind: hide the malicious agent until the end" checked={opts.blind} onChange={set("blind")} />
      <div className="round-go">
        <Button onClick={() => { setShowOpts(false); randomize(true); }} disabled={busy || !spec.length} iconLeft={<Icon name="arrow-right" size={16} />}>Start round</Button>
        <Button variant="secondary" onClick={() => { setShowOpts(false); randomize(false); }} disabled={busy || !spec.length} iconLeft={<Icon name="refresh" size={16} />}>Randomize only</Button>
        <Button variant="ink" onClick={() => { setShowOpts(false); randomize(true, "crisis"); }} disabled={busy || !spec.length} iconLeft={<Icon name="siren" size={16} />}>Crisis</Button>
      </div>
      <p className="ar-caption muted">Start round draws the agents and the call begins. Randomize only draws them so you can look first, then press Start the call. Crisis makes two or more agents rogue at once and the system has to notice, adapt and act.</p>
      {!spec.length && <p className="ar-caption" style={{ color: "var(--status-negative)" }}>No agent blocks on the board. Pick 3 · 5 · 8 above or build the workflow on the Build tab.</p>}
    </div>
  );

  return (
    <div className="round-page">
      <div className="round-col round-col--control">
        <Card padding={16} eyebrow="NEW ROUND">
          {round && !showOpts ? (
            <div className="round-controls" style={{ marginTop: 0 }}>
              <Button onClick={() => randomize(true)} disabled={busy || !spec.length} iconLeft={<Icon name="arrow-right" size={16} />}>Start round</Button>
              <Button variant="secondary" size="sm" onClick={() => randomize(false)} disabled={busy || !spec.length} iconLeft={<Icon name="refresh" size={14} />}>Randomize only</Button>
              <Button variant="ink" size="sm" onClick={() => randomize(true, "crisis")} disabled={busy || !spec.length} iconLeft={<Icon name="siren" size={14} />} title="Two or more agents go rogue at once">Crisis</Button>
              <Button variant="ghost" size="sm" onClick={() => setShowOpts(true)}>Options</Button>
              <Button variant="ghost" size="sm" onClick={reset} disabled={busy} iconLeft={<Icon name="x" size={14} />}>Reset</Button>
              <span className="ar-caption muted" style={{ alignSelf: "center" }}>
                {spec.length} agents on the board · rogue {opts.rogue === "pick" ? "chosen" : opts.rogue === "none" ? "none" : opts.rogue === "crisis" ? "crisis" : "coin"} · {opts.agents === "hr" ? "Real LLM" : "Forced LLM"}
              </span>
            </div>
          ) : optionsForm}
        </Card>
        {err && <ErrorNote error={err} />}
        {round && (
          <Card padding={16} eyebrow={`ROUND ${round.id} · ${round.status.toUpperCase()}`}>
            <div className="round-truth">
              {truth.hidden ? <Badge tone="sand">{truth.crisis ? `Crisis: ${truth.count} rogues, hidden until the end` : "Malicious agent hidden until the end"}</Badge>
                : truth.rogues ? <div className="ar-small"><Badge tone="ink" dot>Crisis: {truth.rogues.length} of {round.seats.length} rogue</Badge>
                    <ul className="crisis-rogues">{truth.rogues.map((r) => <li key={r.seat}><b>{r.agent}</b> <span className="muted">({r.role})</span>: {r.label}</li>)}</ul></div>
                : truth.malicious ? <span className="ar-small"><Badge tone="ink" dot>Rogue: {malSeat?.agent}</Badge> <b>{truth.label}</b> <span className="muted">({malSeat?.role}, {truth.chosen_by === "person" ? "chosen by you" : "coin"})</span></span>
                : <Badge tone="positive">No malicious agent this round</Badge>}
            </div>
            {active && <SpeedSlider id="rd-live-speed" pace={round.options.pace} delay={round.options.delay}
              onChange={(sp) => { setOpts((o) => ({ ...o, pace: sp.pace, delay: sp.delay ?? o.delay })); act(() => api.roundPace(round.id, sp.pace, sp.delay ?? undefined)); }} />}
            <div className="round-controls">
              {round.status === "waiting" && <Button size="sm" disabled={busy} onClick={next} iconLeft={<Icon name="arrow-right" size={15} />}>
                {round.waiting_for === "start" ? "Start the call" : round.waiting_for === "before_call" ? "Place the call" : round.waiting_for === "before_notify" ? "Send the notices" : "Next action"}</Button>}
              {active && <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => api.roundStop(round.id))}>Stop</Button>}
              <Button size="sm" variant="ghost" disabled={busy} onClick={reset} iconLeft={<Icon name="x" size={14} />}>Reset</Button>
              {truth.hidden && <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => api.roundReveal(round.id))}>Reveal</Button>}
              {round.status === "waiting" && <span className="ar-caption muted" style={{ alignSelf: "center" }}>or press →</span>}
            </div>
            {round.options?.agents === "hr" && hrEv && (
              <p className="ar-caption muted" style={{ marginTop: 8 }}>{hrEv.kind === "hr_error" ? "⚠ " : ""}{hrEv.text}</p>
            )}
          </Card>
        )}
        {!round && <p className="ar-caption muted" style={{ padding: "4px 4px 0" }}>The round runs through the workflow on the board: one random agent per block, maybe one of them malicious (a coin, none, or you choose which and what it does). AngryRobot watches every agent without knowing.</p>}
      </div>

      <div className="round-col round-col--main">
        {liveCall && <LiveCallFlow call={liveCall} />}
        {canvas && <Card padding={8} eyebrow="THE WORKFLOW · FROM THE BUILD TAB">{canvas}</Card>}
        {round ? (
          <>
            <CrisisBanner round={round} />
            <Card padding={14} eyebrow="IRA OF EVERY ACTION">
              <IraMap round={round} selected={shown?.i} onSelect={setPinned} />
            </Card>

            {shown && (
              <Card padding={14} eyebrow={pinned != null ? "SELECTED ACTION" : "LAST ACTION"}>
                {pinned != null && <Button size="sm" variant="ghost" style={{ float: "right", marginTop: -34 }} onClick={() => setPinned(null)}>Follow the latest</Button>}
                <Decision ev={shown} events={events} round={round} />
              </Card>
            )}

            <NoticesCard round={round} waiting={round.status === "waiting" && round.waiting_for === "before_notify"} />
            {round.crisis && <OperatorsCard round={round} />}
            {outcome && (
              <Card padding={16} eyebrow="OUTCOME" ground={outcome.met_expectation ? "paper" : "sand"}>
                <Badge tone={(OUTCOME[outcome.label] || [])[0]}>{(OUTCOME[outcome.label] || [outcome.label])[1]}</Badge>
                <p className="ar-small" style={{ marginTop: 10 }}>{outcome.summary}</p>
                <CrisisOutcome outcome={outcome} round={round} />
              </Card>
            )}
            {round.status === "stopped" && !outcome && <p className="ar-caption muted">Round stopped before the end: it does not count in the stats.</p>}
            {callEv && (
              <Card padding={16} eyebrow="LAST TRIGGER · HAPPYROBOT CALL" ground={callEv.status === "sent" ? "paper" : "sunken"}>
                <Badge tone={callEv.status === "sent" ? "positive" : callEv.status === "dialing" ? "info" : callEv.status === "failed" ? "negative" : "neutral"}>{callEv.status}</Badge>
                <p className="ar-small" style={{ marginTop: 10 }}>{callEv.text}</p>
              </Card>
            )}
          </>
        ) : <p className="ar-caption muted" style={{ padding: "4px 4px 0" }}>The IRA of every action will show up here once a round starts, and each block above shows who sits there and how it goes.</p>}
      </div>

      <div className="round-col round-col--data">
        <LiveCallsCard live={live} />
        <DataCard live={live} refreshKey={`${round?.id}-${round?.status}`} />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- real phone calls (angryrobot/live_call.py)
   Whoever calls the demo number talks to a random agent; here: whether that agent is malicious (coin, always,
   never, and optionally which behaviour), and every call so far with its agent, worst verdict and alert call. */
const LIVE_MODES = [{ value: "random", label: "Coin (50 %)" }, { value: "force", label: "Always malicious" }, { value: "none", label: "Never" }];
function LiveCallsCard({ live }) {
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => { if (!live) return undefined; const t = setInterval(() => setTick((n) => n + 1), 2000); return () => clearInterval(t); }, [live]);
  const [cfg, reload] = useAsync(() => (live ? api.liveSettings() : Promise.resolve(null)), [live]);
  const [list] = useAsync(() => (live ? api.liveCalls(12) : Promise.resolve(null)), [live, tick]);
  const [err, setErr] = React.useState(null);
  if (!live) return null;
  if (cfg.error?.status === 404) return null;   // service without live calls yet
  const s = cfg.data;
  const save = async (mode, trait) => { setErr(null); try { await api.setLiveSettings(mode, trait); reload(); } catch (x) { setErr(x); } };
  const calls = list.data?.calls || [];
  return (
    <Card padding={16} eyebrow="REAL PHONE CALLS">
      <p className="ar-caption muted">Whoever calls the demo number talks to a random agent. AngryRobot audits every sentence; on a KILL, HappyRobot calls {s?.alert?.phone || "the alert number"}.</p>
      {s && (
        <>
          <div className="seg" role="radiogroup" aria-label="Is the agent malicious" style={{ marginTop: 10 }}>
            {LIVE_MODES.map((m) => <button key={m.value} role="radio" aria-checked={s.mode === m.value} className={s.mode === m.value ? "is-on" : ""}
                                             onClick={() => save(m.value, m.value === "force" ? s.trait : null)}>{m.label}</button>)}
          </div>
          {s.mode === "force" && (
            <div style={{ marginTop: 10 }}>
              <Select id="live-trait" label="What it does" value={s.trait || ""} onChange={(e) => save("force", e.target.value)}
                      options={[{ value: "", label: "Random behaviour" }, ...Object.entries(s.traits || {}).map(([k, t]) => ({ value: k, label: `${t.label}${s.tool_traits?.[k] ? " (needs a tool in HappyRobot)" : ""}` }))]} />
            </div>
          )}
          <p className="ar-caption muted" style={{ marginTop: 8 }}>Alert: {s.alert?.api_key && s.alert?.workflow ? "ready" : "not configured on the service"} · “{s.alert?.message}”</p>
        </>
      )}
      {err && <ErrorNote error={err} />}
      <div style={{ marginTop: 10 }}>
        {calls.length ? calls.map((c) => (
          <div key={c.run_id} className="kv" style={{ alignItems: "flex-start" }}>
            <div>
              <b>{c.persona.agent}</b> <span className="muted">· {c.persona.role} · {c.turns} turns</span>
              <div className="ar-caption muted">{c.persona.malicious ? `Malicious: ${c.persona.malicious_label}` : "Not malicious"}{c.alert ? ` · alert ${c.alert.status}` : ""}</div>
            </div>
            <Verdict v={c.worst} />
          </div>
        )) : <p className="ar-caption muted">No calls yet. Call the demo number.</p>}
      </div>
    </Card>
  );
}

/* ---------------------------------------------------------------- data: stats, downloads, learning (a person approves) */
export function DataCard({ live, refreshKey }) {
  const [s] = useAsync(() => (live ? api.roundStats() : Promise.resolve(null)), [live, refreshKey]);
  const [rep, reload] = useAsync(() => (live ? api.learnReport() : Promise.resolve(null)), [live, refreshKey]);
  const [cr] = useAsync(() => (live ? api.crisisReport().catch(() => null) : Promise.resolve(null)), [live, refreshKey]);
  const cx = cr.data;
  const [msg, setMsg] = React.useState(null);
  const [open, setOpen] = React.useState(false);
  const d = s.data; const r = rep.data;
  const get = async (fmtx) => { setMsg(null); try { await download(`/v1/rounds/export?format=${fmtx}`, fmtx === "csv" ? "angryrobot-actions.csv" : "angryrobot-rounds.jsonl"); } catch (x) { setMsg(x.message); } };
  const apply = async () => { try { const out = await api.learnApply(r.proposed_judge_weights); setMsg(`Applied. Paste into config.yaml to keep it after a restart:\n${out.yaml}`); reload(); } catch (x) { setMsg(x.message); } };
  const reset = async () => { try { await api.learnReset(); setMsg("Back to the config.yaml weights."); reload(); } catch (x) { setMsg(x.message); } };
  return (
    <Card padding={16} eyebrow={d?.rounds ? `DATA · ${d.rounds} FINISHED ROUNDS` : "DATA"}>
      {d?.rounds ? (
        <>
          <div className="kv"><span className="ar-small muted">Malicious agent blocked or killed</span><span className="num">{d.round_recall ?? "—"}</span></div>
          <div className="kv"><span className="ar-small muted">False alarm in rounds with no malicious agent</span><span className="num">{d.false_alarm_rate ?? "—"}</span></div>
          <div className="kv"><span className="ar-small muted">Benign actions blocked</span><span className="num">{d.action?.false_positive_rate ?? "—"}</span></div>
        </>
      ) : <p className="ar-caption muted">No finished rounds yet.</p>}
      {cx?.crises ? (
        <div className="kv" style={{ alignItems: "flex-start" }}>
          <span className="ar-small muted">Crises · {cx.crises}: first notice right · order agreement · detected</span>
          <span className="num" style={{ whiteSpace: "nowrap" }}>{cx.first_notice_right ?? "—"} · {cx.order_agreement ?? "—"} · {cx.detection_rate ?? "—"}</span>
        </div>
      ) : null}
      <div className="round-controls">
        <Button size="sm" variant="secondary" onClick={() => get("csv")} iconLeft={<Icon name="arrow-right" size={14} style={{ transform: "rotate(90deg)" }} />}>Actions (CSV)</Button>
        <Button size="sm" variant="secondary" onClick={() => get("jsonl")} iconLeft={<Icon name="arrow-right" size={14} style={{ transform: "rotate(90deg)" }} />}>Rounds (JSONL)</Button>
      </div>
      <p className="ar-caption muted" style={{ marginTop: 8 }}>CSV: one row per audited action with its verdict, IRA, signals, judge scores, the round's truth and your label. Ready to train or analyse.</p>
      {r && (
        <div style={{ marginTop: 14 }}>
          <button className="dec-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <Icon name="chevron-right" size={14} style={{ transform: open ? "rotate(90deg)" : "none" }} />
            Learning: {r.false_positives} false alarms, {r.false_negatives} misses over {r.labelled_actions} labelled actions
          </button>
          {open && (
            <div className="dec-body">
              {r.worst_signals?.length > 0 && (
                <div className="why-block">
                  <span className="ar-overline muted">Signals that fire on benign actions</span>
                  {r.worst_signals.map((x) => <div key={x.signal} className="why-sig"><span className="code">{x.signal}</span><span className="ar-mono num why-pw">{x.on_benign} benign · {x.on_rogue} rogue</span></div>)}
                </div>
              )}
              <div className="why-block">
                <span className="ar-overline muted">Judge weights</span>
                {Object.entries(r.judge_weights || {}).map(([k, v]) => (
                  <div key={k} className="why-sig"><span className="code">{k}</span>
                    <span className="ar-mono num why-pw">{v}{r.proposed_judge_weights ? ` → ${r.proposed_judge_weights[k]}` : ""}</span></div>
                ))}
                {r.proposed_judge_weights
                  ? <div className="round-controls"><Button size="sm" onClick={apply}>Apply the proposed weights</Button><Button size="sm" variant="ghost" onClick={reset}>Reset</Button></div>
                  : <p className="ar-caption muted">{r.needs}</p>}
              </div>
            </div>
          )}
        </div>
      )}
      {msg && <pre className="code" style={{ marginTop: 10, whiteSpace: "pre-wrap" }}>{msg}</pre>}
    </Card>
  );
}
export { SEV };
