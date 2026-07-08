// The live §4 control rail. Four sliders map onto pipeline knobs (recency half-life,
// source mix, velocity bias, MMR lambda); topic chips cycle boost / mute / neutral.
// Every change flows up; the app debounces and re-ranks.

import {
  isNeutral,
  NEUTRAL_PREFS,
  type PreferenceState,
} from "../app/preferences";
import { fixed } from "./format";
import styles from "./PreferenceRail.module.css";

interface Knob {
  key: "recency" | "friends_global" | "niche_viral" | "exploration";
  name: string;
  left: string;
  right: string;
  map: string;
}

const KNOBS: Knob[] = [
  { key: "recency", name: "Recency", left: "Popularity", right: "Recency", map: "decay half-life" },
  { key: "friends_global", name: "Source mix", left: "Friends", right: "Global", map: "in/out-network boost" },
  { key: "niche_viral", name: "Reach", left: "Niche", right: "Viral", map: "velocity bias" },
  { key: "exploration", name: "Exploration", left: "Focused", right: "Explore", map: "MMR λ" },
];

interface PreferenceRailProps {
  state: PreferenceState;
  topics: string[];
  disabled?: boolean;
  onChange: (next: PreferenceState) => void;
}

export function PreferenceRail({ state, topics, disabled, onChange }: PreferenceRailProps) {
  const setKnob = (key: Knob["key"], value: number) => onChange({ ...state, [key]: value });

  const cycleTopic = (topic: string) => {
    const current = state.topic_weights[topic] ?? 0.5;
    // neutral -> boost -> mute -> neutral
    const next = current === 0.5 ? 1 : current === 1 ? 0 : 0.5;
    const topic_weights = { ...state.topic_weights };
    if (next === 0.5) delete topic_weights[topic];
    else topic_weights[topic] = next;
    onChange({ ...state, topic_weights });
  };

  return (
    <div className={styles.rail}>
      <div className={styles.group}>
        {KNOBS.map((knob) => {
          const value = state[knob.key];
          return (
            <div key={knob.key} className={styles.slider}>
              <div className={styles.knobHead}>
                <span className={styles.knobName}>{knob.name}</span>
                <span className={styles.knobMap}>{knob.map}</span>
              </div>
              <input
                type="range"
                className={styles.range}
                min={0}
                max={1}
                step={0.01}
                value={value}
                disabled={disabled}
                onChange={(event) => setKnob(knob.key, Number(event.target.value))}
              />
              <div className={styles.sliderLabels}>
                <span className={value < 0.5 ? styles.sliderLabelActive : ""}>{knob.left}</span>
                <span className={value > 0.5 ? styles.sliderLabelActive : ""}>{knob.right}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div className={styles.divider} />

      <div className={styles.group}>
        <div className={styles.topicsHead}>
          <span className={styles.topicsTitle}>Topic weights</span>
          <button
            className={styles.reset}
            disabled={disabled || isNeutral(state)}
            onClick={() => onChange(NEUTRAL_PREFS)}
          >
            Reset all
          </button>
        </div>
        {topics.length === 0 ? (
          <span className={styles.topicHint}>
            No topic centroids yet — run <span className="mono">make centroids</span>.
          </span>
        ) : (
          <>
            <div className={styles.topics}>
              {topics.map((topic) => {
                const weight = state.topic_weights[topic] ?? 0.5;
                const cls =
                  weight > 0.5 ? styles.topicBoosted : weight < 0.5 ? styles.topicMuted : "";
                return (
                  <button
                    key={topic}
                    className={`${styles.topic} ${cls}`}
                    disabled={disabled}
                    onClick={() => cycleTopic(topic)}
                  >
                    {topic}
                    {weight !== 0.5 && (
                      <span className={styles.topicWeight}>{fixed(weight, 1)}</span>
                    )}
                  </button>
                );
              })}
            </div>
            <span className={styles.topicHint}>
              Click to cycle boost → mute → neutral. Weights blend the topic centroids into
              a query vector scored by cosine similarity.
            </span>
          </>
        )}
      </div>
    </div>
  );
}
