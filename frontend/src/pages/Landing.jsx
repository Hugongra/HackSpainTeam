/* Marketing surface, minimal cut: a full-bleed animated hero carrying the tagline, a video slot and
   the one call to action. No info sections below the fold — that content lives in the console. */
import React from "react";
import { Button, Icon, Logo } from "../ds";

const go = (hash) => () => { window.location.hash = hash; };

function Nav() {
  return (
    <div className="nav-shell nav-shell--dark">
      <div className="nav-pill">
        <a href="#/" aria-label="AngryRobot home" style={{ display: "inline-flex" }}><Logo variant="lockup" tone="paper" height={22} /></a>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <Button size="sm" variant="inverse" onClick={go("#/console")}>Open console</Button>
        </div>
      </div>
    </div>
  );
}

function VideoSlot() {
  return (
    <div className="video-slot" aria-label="AngryRobot introduction video, coming soon">
      <span className="video-slot-play"><Icon name="zap" size={22} /></span>
      <span className="ar-mono" style={{ color: "var(--text-on-dark-muted)" }}>VIDEO COMING SOON</span>
    </div>
  );
}

function Hero() {
  return (
    <section className="hero hero--full" data-ground="dark">
      <div className="hero-bg" aria-hidden>
        <span className="hero-glow hero-glow--a" />
        <span className="hero-glow hero-glow--b" />
      </div>
      <div className="wrap hero-inner hero-inner--center">
        <h1 className="ar-display" style={{ maxWidth: "16ch", textAlign: "center", marginInline: "auto" }}>
          The anger management layer for your agents
        </h1>
        <VideoSlot />
        <div style={{ display: "flex", justifyContent: "center", marginTop: 40 }}>
          <Button size="lg" variant="inverse" onClick={go("#/console")} iconRight={<Icon name="arrow-right" size={18} />}>
            Open the console
          </Button>
        </div>
      </div>
    </section>
  );
}

export default function Landing() {
  return (
    <>
      <Nav />
      <Hero />
    </>
  );
}
