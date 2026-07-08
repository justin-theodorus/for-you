// Per-action predicted-probability bars (like/reply/repost/quote/dwell) — the model's
// raw output, before the weighted collapse into the final score.

import { ACTION_KEYS, type ActionScores } from "../api/types";
import { actionColor } from "./format";
import { Meter } from "./primitives";

export function ActionScoreBars({ scores }: { scores: ActionScores }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {ACTION_KEYS.map((key) => (
        <Meter
          key={key}
          label={key}
          value={scores[key]}
          display={scores[key].toFixed(2)}
          color={actionColor(key)}
        />
      ))}
    </div>
  );
}
