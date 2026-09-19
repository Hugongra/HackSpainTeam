/* Marketing surface, minimal cut: full-bleed hero, a scroll-revealed swarm of agent chips, the video
   slot in a glass frame, then the one call to action. Everything pops in with an overshoot bounce —
   no fades. No info sections — that content lives in the console. */
import React from "react";
import { Button, Icon, Logo } from "../ds";

const go = (hash) => () => { window.location.hash = hash; };

/** Pops `children` in with an overshoot bounce once scrolled into view (or immediately if `eager`). */
function Reveal({ children, className = "", style, delay = 0, eager = false, as: As = "div" }) {
  const ref = React.useRef(null);
  const [on, setOn] = React.useState(eager);
  React.useEffect(() => {
    if (eager) return undefined;
    const el = ref.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) setOn(true); }, { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, [eager]);
  return (
    <As ref={ref} className={`${className} ${on ? "pop-in" : "pop-pending"}`} style={{ animationDelay: `${delay}ms`, ...style }}>
      {children}
    </As>
  );
}

function Nav() {
  return (
    <div className="nav-shell nav-shell--dark">
      <div className="nav-pill">
        <a href="#/" aria-label="AngryRobot home" style={{ display: "inline-flex" }}><Logo variant="lockup" tone="paper" height={22} /></a>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <Button size="sm" variant="inverse" className="pop-hover" onClick={go("#/console")}>Open console</Button>
        </div>
      </div>
    </div>
  );
}

function Hero() {
  const scrollNext = () => document.getElementById("swarm")?.scrollIntoView({ behavior: "smooth" });
  return (
    <section className="hero hero--full" data-ground="dark">
      <div className="hero-bg" aria-hidden>
        <span className="hero-glow hero-glow--a" />
        <span className="hero-glow hero-glow--b" />
      </div>
      <div className="wrap hero-inner hero-inner--center">
        <Reveal as="h1" eager className="ar-display" style={{ maxWidth: "16ch", textAlign: "center", marginInline: "auto" }}>
          The anger management layer for your agents
        </Reveal>
      </div>
      <button type="button" className="scroll-cue pop-hover" onClick={scrollNext} aria-label="Scroll down">
        <span className="ar-mono">SCROLL</span>
        <Icon name="chevron-down" size={22} />
      </button>
    </section>
  );
}

/** ~18 agent chips, mostly calm (green), a few rogue (red) — pop in one by one, each with its own tilt. */
function AgentSwarm() {
  const ref = React.useRef(null);
  const [visible, setVisible] = React.useState(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) setVisible(true); }, { threshold: 0.2 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const chips = React.useMemo(() => {
    const rogueAt = new Set([2, 7, 11, 15]);
    return Array.from({ length: 18 }, (_, i) => ({
      bad: rogueAt.has(i),
      size: 52 + ((i * 37) % 40),
      lift: (i % 3) * 16,
      rot: ((i * 53) % 34) - 17,
    }));
  }, []);
  return (
    <section id="swarm" className="band-dark swarm-section" data-ground="dark">
      <div ref={ref} className="swarm-grid">
        {chips.map((c, i) => (
          <span key={i}
                className={`swarm-chip pop-hover ${c.bad ? "is-bad" : "is-good"} ${visible ? "pop-in" : "pop-pending"}`}
                style={{ width: c.size, height: c.size, marginTop: c.lift, "--rot": `${c.rot}deg`, animationDelay: `${i * 70}ms` }}>
            <Icon name={c.bad ? "octagon" : "check"} size={Math.round(c.size * 0.4)} />
          </span>
        ))}
      </div>
    </section>
  );
}

function VideoSection() {
  return (
    <section className="band-dark video-section" data-ground="dark">
      <div className="wrap" style={{ display: "flex", justifyContent: "center" }}>
        <Reveal className="video-slot pop-hover">
          <span className="video-slot-play"><Icon name="zap" size={22} /></span>
          <span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>VIDEO COMING SOON</span>
        </Reveal>
      </div>
    </section>
  );
}

function ConsoleCta() {
  return (
    <section className="band-dark" data-ground="dark" style={{ padding: "0 0 clamp(80px,10vw,120px)" }}>
      <div className="wrap" style={{ display: "flex", justifyContent: "center" }}>
        <Reveal>
          <Button size="lg" variant="inverse" className="pop-hover" onClick={go("#/console")} iconRight={<Icon name="arrow-right" size={18} />}>
            Open the console
          </Button>
        </Reveal>
      </div>
    </section>
  );
}

export default function Landing() {
  return (
    <>
      <Nav />
      <Hero />
      <AgentSwarm />
      <VideoSection />
      <ConsoleCta />
    </>
  );
}
