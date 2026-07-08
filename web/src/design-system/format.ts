// Small pure formatting/deterministic helpers shared across the design system.

import type { FeedItem } from "../api/types";

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
  in_network: "var(--src-in)",
  out_of_network: "var(--src-out)",
  trending: "var(--src-trend)",
};

export function sourceColor(source: string): string {
  return SOURCE_VARS[source] ?? "var(--ink-dim)";
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

// The gradient body for a deterministic avatar, matching the template's hues.
export function avatarGradient(handle: string): string {
  const hue = hueFromString(handle);
  return `linear-gradient(140deg, hsl(${hue} 42% 52%), hsl(${(hue + 40) % 360} 40% 42%))`;
}

interface ReaderReason {
  primarySource: string;
  label: string;
  sentence: string;
}

const READER_REASONS: Record<string, Omit<ReaderReason, "primarySource">> = {
  in_network: {
    label: "From someone you follow",
    sentence:
      "This is from an account you follow. It ranked high because your engagement history and its recency scored well.",
  },
  trending: {
    label: "Trending now",
    sentence:
      "This is spiking in engagement across the network right now, so it surfaced even though you don't follow the author.",
  },
  out_of_network: {
    label: "Discovery — out of network",
    sentence:
      "You don't follow this author. It's a discovery pick, matched to your interests by embedding similarity.",
  },
};

// Plain-language "why am I seeing this" for the Reader view, derived from the item's
// highest-scoring source. No inference beyond picking the dominant provenance.
export function readerReason(item: FeedItem): ReaderReason {
  const sources = item.why.sources;
  const primary =
    sources.length > 0
      ? sources.reduce((best, tag) => (tag.score > best.score ? tag : best)).source
      : "out_of_network";
  const copy = READER_REASONS[primary] ?? READER_REASONS.out_of_network!;
  return { primarySource: primary, ...copy };
}
