// Small pure formatting/deterministic helpers shared across the design system.

export function fixed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

export function compact(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

export function initials(name: string): string {
  const parts = name.trim().split(/[\s_]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
}

// Deterministic hue from a handle, for avatars — no per-user color stored server-side.
export function hueFromString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) % 360;
  }
  return hash;
}

const SOURCE_VARS: Record<string, string> = {
  in_network: "var(--src-in-network)",
  out_of_network: "var(--src-out-of-network)",
  trending: "var(--src-trending)",
};

export function sourceColor(source: string): string {
  return SOURCE_VARS[source] ?? "var(--text-muted)";
}

const ACTION_VARS: Record<string, string> = {
  like: "var(--act-like)",
  reply: "var(--act-reply)",
  repost: "var(--act-repost)",
  quote: "var(--act-quote)",
  dwell: "var(--act-dwell)",
};

export function actionColor(action: string): string {
  return ACTION_VARS[action] ?? "var(--accent)";
}
