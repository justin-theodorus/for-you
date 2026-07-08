// Preference-rail state model and its mapping to the API payload.
// Mirrors the neutral-is-no-op contract of the Python Preferences layer (plan.md §4):
// every knob centres at 0.5, and a fully-neutral state sends values the backend collapses
// back to the untuned feed.

import type { Preferences } from "../api/types";

export interface PreferenceState {
  recency: number;
  friends_global: number;
  niche_viral: number;
  exploration: number; // 0.5 = auto (no MMR override)
  topic_weights: Record<string, number>; // topic -> [0,1]; absent = neutral 0.5
}

export const NEUTRAL_PREFS: PreferenceState = {
  recency: 0.5,
  friends_global: 0.5,
  niche_viral: 0.5,
  exploration: 0.5,
  topic_weights: {},
};

export function isNeutral(state: PreferenceState): boolean {
  return (
    state.recency === 0.5 &&
    state.friends_global === 0.5 &&
    state.niche_viral === 0.5 &&
    state.exploration === 0.5 &&
    Object.values(state.topic_weights).every((weight) => weight === 0.5)
  );
}

export function toPayload(state: PreferenceState): Preferences {
  const topicWeights: Record<string, number> = {};
  for (const [name, weight] of Object.entries(state.topic_weights)) {
    if (weight !== 0.5) topicWeights[name] = weight;
  }
  return {
    recency: state.recency,
    friends_global: state.friends_global,
    niche_viral: state.niche_viral,
    exploration: state.exploration === 0.5 ? null : state.exploration,
    topic_weights: topicWeights,
  };
}
