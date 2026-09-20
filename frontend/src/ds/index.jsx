/* AngryRobot design system primitives, ported from the "Angry Robots logo rework" kit.
   Same APIs and styling as components/*.jsx; icons come from lucide-react (the kit's
   flagged substitution) at the brand's 1.75 stroke. */
import React from "react";
import {
  Activity, AlertTriangle, ArrowRight, BookOpen, Brain, Check, ChevronDown, ChevronRight, Copy, Eye, FlaskConical,
  Gauge, Hand, Maximize2, Minimize2, Octagon, Phone, Plug, RefreshCw, Search, Settings, ShieldAlert, Siren, Terminal,
  Wrench, X, Zap,
} from "lucide-react";

const ICONS = {
  activity: Activity, "alert-triangle": AlertTriangle, "arrow-right": ArrowRight, "book-open": BookOpen,
  brain: Brain, check: Check, "chevron-down": ChevronDown, "chevron-right": ChevronRight, copy: Copy, eye: Eye,
  flask: FlaskConical, gauge: Gauge, hand: Hand, maximize: Maximize2, minimize: Minimize2, octagon: Octagon,
  phone: Phone, plug: Plug, refresh: RefreshCw, search: Search, settings: Settings, "shield-alert": ShieldAlert,
  siren: Siren, terminal: Terminal, wrench: Wrench, x: X, zap: Zap,
};

export function Icon({ name, size = 20, strokeWidth = 1.75, style }) {
  const Glyph = ICONS[name];
  if (!Glyph) return null;
  return <Glyph size={size} strokeWidth={strokeWidth} aria-hidden style={{ flex: "none", ...style }} />;
}

const SRC = "M173 121.106C173 111.395 167.675 102.465 159.13 97.8492L146.43 90.9886C137.886 86.3728 132.561 77.4433 132.561 67.7318V0H86V52.921C86 62.6325 91.3253 71.5619 99.8697 76.1778L112.57 83.0384C121.114 87.6543 126.439 96.5838 126.439 106.295V137H173V121.106Z";

/** The AngryRobot mark and lockup. Never re-draw either — use this. */
export function Logo({ variant = "lockup", tone = "ink", height = 32, style }) {
  const id = React.useId().replace(/:/g, "");
  const color = tone === "paper" ? "var(--ar-paper)" : "var(--ar-black)";
  const mark = (
    <svg viewBox="0 0 144 137" height={height} width={(height * 144) / 137} style={{ display: "block", flex: "none" }}
         aria-hidden={variant === "lockup"} role={variant === "lockup" ? undefined : "img"}>
      {variant === "lockup" ? null : <title>AngryRobot</title>}
      <mask id={id}>
        <rect x={-20} y={-20} width={200} height={200} fill="#fff" />
        <circle cx={72} cy={63} r={24} fill="#000" />
      </mask>
      <g fill={color} mask={`url(#${id})`}>
        <g transform="translate(-86,137) scale(1,-1)"><path d={SRC} /></g>
        <g transform="translate(230,137) scale(-1,-1)"><path d={SRC} /></g>
      </g>
    </svg>
  );
  if (variant === "mark") return <span style={{ display: "inline-flex", ...style }}>{mark}</span>;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: height * 0.34, color, ...style }}>
      {mark}
      <span style={{ fontFamily: "var(--font-sans)", fontWeight: 500, fontSize: height * 0.82, letterSpacing: "-0.025em",
                     lineHeight: 1, whiteSpace: "nowrap" }}>AngryRobot</span>
    </span>
  );
}

const GLASS = {
  dark: { background: "var(--glass-fill)", border: "1px solid var(--glass-border)", color: "var(--glass-text)",
          boxShadow: "var(--glass-highlight), var(--glass-shadow)" },
  strong: { background: "var(--glass-fill-strong)", border: "1px solid var(--glass-border)", color: "var(--glass-text)",
            boxShadow: "var(--glass-highlight), var(--glass-shadow)" },
  accent: { background: "var(--glass-fill-accent)", border: "1px solid var(--glass-border-accent)", color: "var(--glass-text)",
            boxShadow: "var(--glass-highlight), var(--glass-shadow)" },
};
const BLURS = { light: "var(--glass-blur-light)", base: "var(--glass-blur)", heavy: "var(--glass-blur-heavy)" };

/** The one frosted surface. Legal only over imagery, video or a dark ground. */
export function GlassPanel({ tone = "dark", blur = "base", radius = "var(--radius-glass)", padding = 24, children, style, ...rest }) {
  const b = BLURS[blur] || BLURS.base;
  return (
    <div style={{ position: "relative", borderRadius: radius, padding, backdropFilter: b, WebkitBackdropFilter: b,
                  ...(GLASS[tone] || GLASS.dark), ...style }} {...rest}>
      {children}
    </div>
  );
}

const SIZES = {
  sm: { height: 34, padding: "0 16px", fontSize: 14, gap: 7 },
  md: { height: 44, padding: "0 24px", fontSize: 16, gap: 9 },
  lg: { height: 54, padding: "0 32px", fontSize: 18, gap: 10 },
};

/** Rounded controls (--radius-sm); surfaces use --radius-lg. */
export function Button({ variant = "primary", size = "md", fullWidth = false, iconLeft, iconRight, children, className = "", style, ...rest }) {
  const s = SIZES[size] || SIZES.md;
  return (
    <button className={`ar-btn ar-btn--${variant} ${className}`}
      style={{ height: s.height, padding: s.padding, fontSize: s.fontSize, gap: s.gap, width: fullWidth ? "100%" : undefined, ...style }}
      {...rest}>
      {iconLeft}{children}{iconRight}
    </button>
  );
}

export function IconButton({ size = "md", label, children, style, ...rest }) {
  const d = { sm: 34, md: 44, lg: 54 }[size] || 44;
  return <Button size={size} aria-label={label} title={label} style={{ width: d, padding: 0, ...style }} {...rest}>{children}</Button>;
}

const GROUNDS = {
  paper: { background: "var(--surface-card)", color: "var(--text-body)" },
  sunken: { background: "var(--surface-sunken)", color: "var(--text-body)" },
  sand: { background: "var(--surface-warm)", color: "var(--ar-black)" },
  signal: { background: "var(--surface-signal)", color: "var(--ar-black)" },
  freight: { background: "var(--surface-freight)", color: "var(--ar-paper)" },
  deep: { background: "var(--surface-deep)", color: "var(--ar-paper)" },
  ink: { background: "var(--surface-inverse)", color: "var(--ar-paper)" },
};

/** Square, hairline-bounded surface. The default container for flat layouts. */
export function Card({ ground = "paper", interactive = false, eyebrow, marker = false, padding, children, style, className = "", ...rest }) {
  const dark = ground === "freight" || ground === "deep" || ground === "ink";
  return (
    <div className={`ar-card ${interactive ? "ar-card--interactive" : ""} ${dark ? "ar-card--dark" : ""} ${className}`}
         style={{ padding: padding ?? "var(--card-pad)", ...(GROUNDS[ground] || GROUNDS.paper), ...style }} {...rest}>
      {(eyebrow || marker) && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 20 }}>
          <span className="ar-mono" style={{ color: dark ? "var(--text-on-dark-muted)" : "var(--text-muted)" }}>{eyebrow}</span>
          {marker && <span style={{ width: 8, height: 8, background: "var(--ar-accent)", flex: "none" }} />}
        </div>
      )}
      {children}
    </div>
  );
}

const BADGES = {
  neutral: { background: "var(--ar-grey-100)", color: "var(--text-body)" },
  positive: { background: "var(--status-positive-soft)", color: "var(--status-positive)" },
  caution: { background: "var(--status-caution-soft)", color: "var(--status-caution)" },
  negative: { background: "var(--status-negative-soft)", color: "var(--status-negative)" },
  info: { background: "var(--status-info-soft)", color: "var(--status-info)" },
  accent: { background: "var(--ar-accent)", color: "var(--text-on-accent)" },
  ink: { background: "var(--ar-black)", color: "var(--ar-paper)" },
  sand: { background: "var(--ar-sand)", color: "var(--ar-black)" },
  onDark: { background: "rgba(244,241,234,0.14)", color: "var(--ar-paper)" },
};

/** Status marker. Mono, uppercase, softly rounded. */
export function Badge({ tone = "neutral", dot = false, children, style }) {
  return (
    <span className="ar-mono" style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 22, padding: "0 9px", borderRadius: "var(--radius-pill)",
                                        whiteSpace: "nowrap", ...(BADGES[tone] || BADGES.neutral), ...style }}>
      {dot && <span style={{ width: 6, height: 6, borderRadius: 3, background: "currentColor", flex: "none" }} />}
      {children}
    </span>
  );
}

export function Tag({ children, style, title }) {
  return (
    <span title={title} style={{ display: "inline-flex", alignItems: "center", gap: 8, minHeight: 26, padding: "2px 10px",
      border: "1px solid var(--border-default)", fontSize: 13, color: "var(--text-body)", background: "var(--surface-card)", ...style }}>
      {children}
    </span>
  );
}

/** Underline tabs. The active rule is the accent (Freight Green) and 2px — the only moving part. */
export function Tabs({ items = [], value, onChange, style }) {
  return (
    <div role="tablist" className="ar-tabs" style={style}>
      {items.map((it) => {
        const on = it.value === value;
        return (
          <button key={it.value} role="tab" aria-selected={on} className={`ar-tab ${on ? "is-on" : ""}`} onClick={() => onChange?.(it.value)}>
            {it.label}
            {it.count !== undefined && <span className="ar-mono" style={{ color: on ? "var(--text-accent)" : "inherit", opacity: on ? 1 : 0.7 }}>{it.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

const TOASTS = { neutral: "var(--ar-grey-500)", positive: "var(--ar-green)", caution: "var(--ar-yellow)", negative: "var(--ar-accent)" };

/** Transient confirmation. Ink panel with a 3px status bar on its leading edge. */
export function Toast({ tone = "neutral", title, onDismiss, children }) {
  return (
    <div role="status" className="ar-toast">
      <span style={{ width: 3, alignSelf: "stretch", background: TOASTS[tone], flex: "none" }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
        {title && <span style={{ fontSize: 15, fontWeight: 500 }}>{title}</span>}
        {children && <span style={{ fontSize: 14, color: "var(--text-on-dark-muted)" }}>{children}</span>}
      </div>
      {onDismiss && <button onClick={onDismiss} aria-label="Dismiss" className="ar-x ar-x--dark">×</button>}
    </div>
  );
}

/** Square text field. Focus is an accent border plus a 3px tinted ring. */
export function Input({ label, hint, id, style, textarea = false, ...rest }) {
  const auto = React.useId();
  const fid = id || auto;
  const Field = textarea ? "textarea" : "input";
  return (
    <label htmlFor={fid} style={{ display: "flex", flexDirection: "column", gap: 8, ...style }}>
      {label && <span style={{ fontSize: 15, fontWeight: 500, color: "var(--text-strong)" }}>{label}</span>}
      <Field id={fid} className="ar-field" {...rest} />
      {hint && <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{hint}</span>}
    </label>
  );
}

export function Select({ label, options = [], id, style, ...rest }) {
  const auto = React.useId();
  const fid = id || auto;
  return (
    <label htmlFor={fid} style={{ display: "flex", flexDirection: "column", gap: 8, ...style }}>
      {label && <span style={{ fontSize: 15, fontWeight: 500, color: "var(--text-strong)" }}>{label}</span>}
      <span style={{ position: "relative", display: "flex" }}>
        <select id={fid} className="ar-field" style={{ appearance: "none", paddingRight: 38, cursor: "pointer" }} {...rest}>
          {options.map((o) => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
        </select>
        <span aria-hidden style={{ position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)", pointerEvents: "none",
                                   color: "var(--text-muted)", fontSize: 12 }}>▾</span>
      </span>
    </label>
  );
}

/** Instant on/off. The only pill-shaped control besides Radio. */
export function Switch({ label, checked, onChange, id }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 12, cursor: "pointer" }}>
      <button type="button" id={id} role="switch" aria-checked={checked} onClick={() => onChange?.(!checked)}
              className={`ar-switch ${checked ? "is-on" : ""}`}><span /></button>
      {label && <span style={{ fontSize: 15, color: "var(--text-body)" }}>{label}</span>}
    </label>
  );
}

/** Modal. Square panel, Terminal Black scrim with a light blur behind it. */
export function Dialog({ open, onClose, title, eyebrow, footer, width = 560, children }) {
  React.useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="ar-scrim" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="ar-dialog" style={{ maxWidth: width }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 20 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {eyebrow && <span className="ar-mono" style={{ color: "var(--text-muted)" }}>{eyebrow}</span>}
            {title && <h3 className="ar-h4">{title}</h3>}
          </div>
          <button onClick={onClose} aria-label="Close" className="ar-x">×</button>
        </div>
        <div>{children}</div>
        {footer && <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, flexWrap: "wrap" }}>{footer}</div>}
      </div>
    </div>
  );
}

/* ---- AngryRobot domain helpers ---------------------------------------- */
export const VERDICT_TONE = { ALLOW: "positive", WARN: "caution", DEFER: "negative", KILL: "ink" };
export const VERDICT_LABEL = { ALLOW: "Allowed", WARN: "Warned", DEFER: "Held", KILL: "Stopped" };

export function Verdict({ v }) {
  if (!v) return null;
  return <Badge tone={VERDICT_TONE[v] || "neutral"} dot={v !== "ALLOW"}>{v}</Badge>;
}
