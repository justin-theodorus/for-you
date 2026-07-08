// Reusable primitives: Panel, Stat, Meter, Pill, SourceBadge, Avatar.
// The atoms every composite inspector component is built from.

import type { CSSProperties, ReactNode } from "react";

import { SOURCE_LABELS } from "../api/types";
import { hueFromString, initials, sourceColor } from "./format";
import styles from "./primitives.module.css";

interface PanelProps {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  bodyClassName?: string;
  className?: string;
  accent?: string;
}

export function Panel({ title, meta, children, bodyClassName, className, accent }: PanelProps) {
  return (
    <section className={`${styles.panel} ${className ?? ""}`}>
      <header className={styles.panelHeader}>
        <span className={styles.panelDot} style={accent ? { background: accent, boxShadow: `0 0 8px ${accent}` } : undefined} />
        <span className={styles.panelTitle}>{title}</span>
        {meta !== undefined && <span className={styles.panelMeta}>{meta}</span>}
      </header>
      <div className={`${styles.panelBody} ${bodyClassName ?? ""}`}>{children}</div>
    </section>
  );
}

export function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  );
}

interface MeterProps {
  label: string;
  value: number;
  /** Fraction in [0,1] used for the fill width; defaults to `value`. */
  fraction?: number;
  display?: string;
  color?: string;
}

export function Meter({ label, value, fraction, display, color }: MeterProps) {
  const width = Math.max(0, Math.min(1, fraction ?? value)) * 100;
  return (
    <div className={styles.meter}>
      <span className={styles.meterLabel}>{label}</span>
      <span className={styles.meterTrack}>
        <span
          className={styles.meterFill}
          style={{ width: `${width}%`, background: color ?? "var(--accent)" }}
        />
      </span>
      <span className={styles.meterValue}>{display ?? value.toFixed(2)}</span>
    </div>
  );
}

export function Pill({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <span className={styles.pill} style={style}>
      {children}
    </span>
  );
}

export function SourceBadge({ source, score }: { source: string; score?: number }) {
  const style = { "--src": sourceColor(source) } as CSSProperties;
  return (
    <span className={styles.sourceBadge} style={style}>
      <span className={styles.sourceDot} />
      {SOURCE_LABELS[source] ?? source}
      {score !== undefined && <span className="mono" style={{ opacity: 0.75 }}>{score.toFixed(2)}</span>}
    </span>
  );
}

export function Avatar({ handle, size = 38 }: { handle: string; size?: number }) {
  const hue = hueFromString(handle);
  const style: CSSProperties = {
    width: size,
    height: size,
    fontSize: size * 0.36,
    background: `linear-gradient(140deg, hsl(${hue} 70% 62%), hsl(${(hue + 40) % 360} 72% 48%))`,
  };
  return (
    <span className={styles.avatar} style={style} aria-hidden>
      {initials(handle)}
    </span>
  );
}
