// Reader-view plain-language controls. Three segmented toggles that set preset values on
// the same §4 preference knobs the Analyst tunes with sliders — the demo's point is that
// both surfaces drive the identical pipeline.

import type { PreferenceState } from "./preferences";
import styles from "./ReaderControls.module.css";

interface Segment {
  label: string;
  left: string;
  right: string;
  key: "recency" | "friends_global" | "exploration";
  leftValue: number;
  rightValue: number;
  isRight: (value: number) => boolean;
}

const SEGMENTS: Segment[] = [
  {
    label: "Freshness",
    left: "Balanced",
    right: "Latest",
    key: "recency",
    leftValue: 0.5,
    rightValue: 0.85,
    isRight: (v) => v > 0.55,
  },
  {
    label: "Sources",
    left: "Following",
    right: "Everyone",
    key: "friends_global",
    leftValue: 0.2,
    rightValue: 0.8,
    isRight: (v) => v >= 0.45,
  },
  {
    label: "Discovery",
    left: "Focused",
    right: "Explore",
    key: "exploration",
    leftValue: 0.2,
    rightValue: 0.85,
    isRight: (v) => v > 0.55,
  },
];

interface ReaderControlsProps {
  state: PreferenceState;
  disabled?: boolean;
  onChange: (next: PreferenceState) => void;
}

export function ReaderControls({ state, disabled, onChange }: ReaderControlsProps) {
  const set = (key: Segment["key"], value: number) => onChange({ ...state, [key]: value });

  return (
    <div className={styles.bar}>
      {SEGMENTS.map((seg) => {
        const right = seg.isRight(state[seg.key]);
        return (
          <div key={seg.key} className={styles.control}>
            <span className="lbl">{seg.label}</span>
            <div className={styles.segmented}>
              <button
                className={`${styles.seg} ${!right ? styles.segActive : ""}`}
                disabled={disabled}
                onClick={() => set(seg.key, seg.leftValue)}
              >
                {seg.left}
              </button>
              <button
                className={`${styles.seg} ${right ? styles.segActive : ""}`}
                disabled={disabled}
                onClick={() => set(seg.key, seg.rightValue)}
              >
                {seg.right}
              </button>
            </div>
          </div>
        );
      })}
      <span className={styles.note}>Same knobs the Analyst tunes — in plain words.</span>
    </div>
  );
}
