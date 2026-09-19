/* Marketing surface. Glass appears twice only — the sticky nav and the hero stat panes, both over
   the dark hero field. Below the fold every surface is a flat, square Card (kit rule). */
import React from "react";
import { Button, Card, GlassPanel, Icon, Logo } from "../ds";
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
          <GlassPanel tone="dark" padding={22}>
            <span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>MALICIOUS AGENTS CAUGHT</span>
            <div className="stat-num num">8 / 8</div>
            <div className="ar-small" style={{ color: "var(--text-on-dark-muted)", marginTop: 6 }}>every rogue agent we've tested it against, stopped</div>
          </GlassPanel>
          <GlassPanel tone="accent" padding={22}>
            <span className="ar-mono" style={{ color: "rgba(244,241,234,0.78)" }}>DANGEROUS ACTIONS THAT SLIPPED THROUGH</span>
            <div className="stat-num num">0</div>
            <div className="ar-small" style={{ color: "rgba(244,241,234,0.78)", marginTop: 6 }}>risky actions are held before they can run</div>
          </GlassPanel>
          <GlassPanel tone="dark" padding={22}>
            <span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>SERVICE</span>
            <div className="stat-num" style={{ fontSize: 30, lineHeight: "46px" }}>{health === null ? "Checking…" : health ? "Online" : "Asleep"}</div>
            <div className="ar-small" style={{ color: "var(--text-on-dark-muted)", marginTop: 6 }}>
              {health ? "live and auditing right now" : "free plan sleeps after 15 min; the console wakes it"}
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
      <Footer />
    </>
  );
}
