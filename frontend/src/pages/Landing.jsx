/* Landing, minimal cut: the glass nav with the logo, and one full-screen video that plays as you
   scroll (the scroll position IS the playhead). A "scroll" cue invites the first move; when the last
   frame — "The final layer for your agents" — is reached, one black button: Open console.
   Nothing else lives here; the console is the product. */
import React from "react";
import { Button, Icon, Logo } from "../ds";

const go = (hash) => () => { window.location.hash = hash; };
const VIDEO = `${import.meta.env.BASE_URL}video/intro.mp4`;
const POSTER = `${import.meta.env.BASE_URL}video/intro-first.jpg`;   // the frame at START_T: HappyRobot already on screen
const LAST = `${import.meta.env.BASE_URL}video/intro-last.jpg`;
const START_T = 0.8;            // s — skip the blank lead-in; the HappyRobot logo is fully drawn here
const SCROLL_VH = 380;          // how many viewport-heights of scroll the whole video spans
const END_AT = 0.965;           // progress at which the last frame counts as reached

function Nav() {
  return (
    <div className="nav-shell nav-shell--dark nav-shell--film">
      <div className="nav-pill">
        <a href="#/" aria-label="AngryRobot home" style={{ display: "inline-flex" }}><Logo variant="lockup" tone="paper" height={22} /></a>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <Button size="sm" variant="inverse" onClick={go("#/console")}>Open console</Button>
        </div>
      </div>
    </div>
  );
}

/** Scroll-driven video: progress through the tall section maps to video.currentTime, eased per frame. */
function ScrollFilm() {
  const secRef = React.useRef(null);
  const vidRef = React.useRef(null);
  const target = React.useRef(0);       // progress the scroll asks for
  const shown = React.useRef(0);        // progress currently on screen (eased toward target)
  const [progress, setProgress] = React.useState(0);
  const [ready, setReady] = React.useState(false);
  const [failed, setFailed] = React.useState(false);   // video unavailable → last frame + button, nothing breaks

  React.useEffect(() => {
    const sec = secRef.current, vid = vidRef.current;
    if (!sec || !vid) return undefined;
    let raf = 0, alive = true;
    // The story depends on scroll position: always start from the top (a refresh would otherwise restore mid-film).
    if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";
    window.scrollTo(0, 0);
    const measure = () => {
      const r = sec.getBoundingClientRect();
      const span = Math.max(1, r.height - window.innerHeight);
      target.current = Math.min(1, Math.max(0, -r.top / span));
    };
    const tick = () => {
      if (!alive) return;
      // ease toward the scroll target so the playhead never jumps
      const d = target.current - shown.current;
      if (Math.abs(d) > 0.0005) {
        shown.current += d * 0.18;
        if (vid.duration && vid.readyState >= 1) {
          const t = START_T + shown.current * (vid.duration - START_T);
          if (Math.abs(vid.currentTime - t) > 1 / 60) vid.currentTime = t;
        }
        setProgress(shown.current);
      }
      raf = requestAnimationFrame(tick);
    };
    const onScroll = () => measure();
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    raf = requestAnimationFrame(tick);
    return () => { alive = false; cancelAnimationFrame(raf); window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); };
  }, []);

  const atEnd = failed || progress >= END_AT;
  const scrollNext = () => window.scrollBy({ top: window.innerHeight * 0.9, behavior: "smooth" });

  return (
    <section ref={secRef} className="film" style={{ height: `${SCROLL_VH}vh` }} aria-label="AngryRobot">
      <div className="film-sticky">
        {failed ? (
          <img className="film-video is-ready" src={LAST} alt="The final layer for your agents" />
        ) : (
          <video ref={vidRef} className={`film-video ${ready ? "is-ready" : ""}`} src={VIDEO} poster={POSTER}
                 muted playsInline preload="auto" onLoadedMetadata={(e) => { e.currentTarget.currentTime = START_T; setReady(true); }} onError={() => setFailed(true)} tabIndex={-1} />
        )}
        {/* invitation to scroll — fades as soon as the film starts */}
        <button type="button" className="film-cue" onClick={scrollNext} aria-label="Scroll down"
                style={{ opacity: progress < 0.04 ? 1 : 0, pointerEvents: progress < 0.04 ? "auto" : "none" }}>
          <span className="ar-mono">SCROLL</span>
          <span className="film-cue-line" />
        </button>
        {/* the one call to action, on the last frame */}
        <div className={`film-end ${atEnd ? "is-on" : ""}`} aria-hidden={!atEnd}>
          <Button size="lg" variant="ink" onClick={go("#/console")} iconRight={<Icon name="arrow-right" size={18} />} tabIndex={atEnd ? 0 : -1}>
            Open console
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
      <ScrollFilm />
    </>
  );
}
