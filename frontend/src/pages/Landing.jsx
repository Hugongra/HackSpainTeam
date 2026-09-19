/* Marketing surface. Glass appears twice only — the sticky nav and the hero stat panes, both over
   the dark hero field. Below the fold every surface is a flat, square Card (kit rule). */
import React from "react";
import { Button, Card, GlassPanel, Icon, Logo, Verdict, VERDICT_LABEL } from "../ds";
import { api } from "../api";

const go = (hash) => () => { window.location.hash = hash; };

/** True while the nav's vertical midline is over an element marked data-ground="dark" (hero, dark bands). */
function useOverDarkGround(ref) {
  const [dark, setDark] = React.useState(true);
  React.useEffect(() => {
    let raf = 0;
    const check = () => {
      raf = 0;
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const mid = r.top + r.height / 2;
      const over = Array.from(document.querySelectorAll('[data-ground="dark"]'))
        .some((g) => { const b = g.getBoundingClientRect(); return b.top <= mid && b.bottom >= mid; });
      setDark(over);
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(check); };
    check();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => { window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); if (raf) cancelAnimationFrame(raf); };
  }, [ref]);
  return dark;
}

function Nav() {
  const ref = React.useRef(null);
  const onDark = useOverDarkGround(ref);
  return (
    <div className={`nav-shell ${onDark ? "nav-shell--dark" : "nav-shell--light"}`}>
      <div ref={ref} className="nav-pill">
        <a href="#/" aria-label="AngryRobot home" style={{ display: "inline-flex" }}><Logo variant="lockup" tone={onDark ? "paper" : "ink"} height={22} /></a>
        <nav className="nav-links" aria-label="Sections">
          <a href="#how">How it audits</a>
          <a href="#score">The IRA score</a>
        </nav>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <Button className="nav-secondary" variant={onDark ? "onDark" : "secondary"} size="sm" onClick={go("#/console/settings/signals")}>Signals</Button>
          <Button size="sm" variant={onDark ? "inverse" : "ink"} onClick={go("#/console")}>Open console</Button>
        </div>
      </div>
    </div>
  );
}

function Hero({ health }) {
  return (
    <section className="hero" data-ground="dark">
      <div className="wrap hero-inner">
        <span className="ar-overline" style={{ color: "var(--text-on-dark-muted)" }}>The layer</span>
        <h1 className="ar-display" style={{ marginTop: 28, maxWidth: "13ch" }}>The anger management layer for your agents</h1>
        <p className="ar-lead" style={{ marginTop: 30, color: "var(--text-on-dark-muted)", maxWidth: "56ch" }}>
          AngryRobot sits above every agent in a workflow and audits each action before it runs: every sentence,
          every tool call, with the agent's own reasoning when the model exposes it. Calm agents pass. Rogue ones are
          held, corrected, or stopped.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 36, flexWrap: "wrap" }}>
          <Button size="lg" variant="inverse" onClick={go("#/console")} iconRight={<Icon name="arrow-right" size={18} />}>Open the console</Button>
        </div>
        <div className="stat-row">
          <GlassPanel tone="dark" padding={26} style={{ display: "flex", flexDirection: "column", gap: 22 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span aria-hidden style={{ width: 8, height: 8, borderRadius: "50%", flex: "none",
                background: health ? "var(--ar-accent)" : "var(--text-on-dark-muted)" }} />
              <span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>
                {health === null ? "Checking the service…" : health ? "Live — auditing every action right now" : "Asleep — opening the console wakes it"}
              </span>
            </div>
            <div>
              <span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>WHAT AN AUDIT CAN DECIDE</span>
              <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginTop: 16 }}>
                {["ALLOW", "WARN", "DEFER", "KILL"].map((v) => (
                  <div key={v} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <Verdict v={v} />
                    <span className="ar-small" style={{ color: "var(--text-on-dark-muted)" }}>{VERDICT_LABEL[v]}</span>
                  </div>
                ))}
              </div>
            </div>
          </GlassPanel>
        </div>
      </div>
    </section>
  );
}

function HowItAudits() {
  const items = [
    ["eye", "During", "Every input is read as it arrives. A caller saying “ignore your instructions”, a tool result carrying hidden orders, a tool that failed: each one taints the actions that follow."],
    ["brain", "Before", "Each sentence and each tool call is audited before it leaves: impact, hard rules, deterministic signals, and an independent judge that also reads the agent's reasoning."],
    ["check", "After", "What the agent said is checked against what the tools actually did. “It's booked” with no successful booking is a finding. Repeat offenders escalate for the whole run."],
  ];
  return (
    <section id="how" className="wrap section">
      <div className="eyebrow-row">
        <span className="ar-overline muted">How it audits</span>
        <h2 className="ar-h2" style={{ maxWidth: "20ch" }}>One audit per action, on three clocks</h2>
      </div>
      <div className="grid-3">
        {items.map(([icon, title, body], i) => (
          <Card key={title} eyebrow={title.toUpperCase()} marker={i === 1}>
            <span style={{ color: "var(--ar-accent)", display: "inline-flex", marginBottom: 18 }}><Icon name={icon} size={26} /></span>
            <h3 className="ar-h4">{title} the action</h3>
            <p className="ar-small muted" style={{ marginTop: 10 }}>{body}</p>
          </Card>
        ))}
      </div>
    </section>
  );
}

function HowItScores() {
  const dims = [
    ["constraint_adherence", 0.60, "Does it break a stated rule — a quote under the price floor, another carrier's data, denying it's an AI?"],
    ["reasoning_integrity", 0.60, "When the agent's own reasoning is visible: does it reveal intent to bend the rules, even if the final action still looks clean?"],
    ["goal_alignment", 0.45, "Is it still serving the workflow's actual goal, or has it started serving someone else's — the caller's, an injected one, its own?"],
    ["scope_escalation", 0.45, "Is it reaching for more power, data or reach than the task needs — an unverified destination, an irreversible step with no confirmation?"],
    ["self_consistency", 0.40, "Does it contradict the conversation so far, or a tool result that already came back — “confirmed” after a tool failed, “no” after “yes”?"],
  ];
  const maxW = Math.max(...dims.map((d) => d[1]));
  return (
    <section id="score" style={{ background: "var(--surface-sunken)" }}>
      <div className="wrap section">
        <div className="eyebrow-row">
          <span className="ar-overline muted">The IRA score</span>
          <h2 className="ar-h2" style={{ maxWidth: "24ch" }}>Impact times suspicion — not a trained classifier</h2>
          <p className="ar-lead muted" style={{ maxWidth: "68ch" }}>
            Two stages are plain deterministic rules: regex catches prompt injection and social-engineering
            phrasing, and a text-similarity check catches an agent looping on the same action. Only one stage
            has a model in it — an independent judge, from a different model family than the agent, scoring
            five dimensions 0–10 with a written reason each time, never picking from a fixed label. A first
            version averaged those five scores and learned the hard way that one clear violation gets diluted
            by four clean ones — so v2 keeps them separate and combines them as suspicion, not an average.
          </p>
        </div>
        <div className="grid-3">
          {dims.map(([name, w, body]) => (
            <Card key={name} eyebrow={`WEIGHT ${w.toFixed(2)}`}>
              <h3 className="ar-h5 code">{name}</h3>
              <div style={{ height: 4, background: "var(--border-subtle)", marginTop: 14, marginBottom: 16 }}>
                <div style={{ height: "100%", width: `${(w / maxW) * 100}%`, background: "var(--ar-accent)" }} />
              </div>
              <p className="ar-small muted">{body}</p>
            </Card>
          ))}
        </div>
        <p className="ar-small muted" style={{ maxWidth: "68ch", marginTop: "var(--card-gap)" }}>
          Suspicion combines every signal — rules and judge alike — with a noisy-OR:
          <span className="code" style={{ color: "var(--text-strong)" }}> 1 − Π(1 − p·w)</span>, so one strong
          signal is enough on its own. A hard rule trigger sets a floor nothing below it can lower. The judge
          can flag and can hold a conversation for review, but acting alone it can never push a verdict all
          the way to KILL — that needs a deterministic signal or a pattern repeating across the session.
        </p>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="wrap" style={{ padding: "48px clamp(16px,4vw,40px)", display: "flex", flexWrap: "wrap", gap: 24,
                                      justifyContent: "space-between", alignItems: "center", borderTop: "1px solid var(--border-subtle)" }}>
      <Logo variant="lockup" tone="ink" height={20} />
      <span className="ar-mono" style={{ color: "var(--text-subtle)" }}>THE ANGER MANAGEMENT LAYER FOR YOUR AGENTS</span>
    </footer>
  );
}

export default function Landing() {
  const [health, setHealth] = React.useState(null);
  React.useEffect(() => {
    let live = true;
    api.health().then((h) => live && setHealth(h)).catch(() => live && setHealth(false));
    return () => { live = false; };
  }, []);
  return (
    <>
      <Nav />
      <Hero health={health} />
      <HowItAudits />
      <HowItScores />
      <Footer />
    </>
  );
}
