// What the last live trigger actually did (plan.md §8): which personas replied, what the
// safety gate blocked, and exactly what it cost. Nothing here is re-derived — it's the
// summary the trigger returned.

import { CAP_REASONS, type LivePostResponse } from "../api/types";
import { Avatar } from "./primitives";
import styles from "./ReactionsPanel.module.css";

export function ReactionsPanel({ last }: { last: LivePostResponse | null }) {
  if (!last) {
    return (
      <p className={styles.empty}>
        Post something and watch the personas respond. Every reply is generated, safety-gated,
        and charged against today’s budget.
      </p>
    );
  }

  const capNote = last.cap_reason ? CAP_REASONS[last.cap_reason] : null;

  return (
    <div className={styles.wrap}>
      <ul className={styles.list}>
        {last.reactions.map((reaction) => (
          <li key={reaction.post_id} className={styles.item}>
            <Avatar handle={reaction.persona_handle} size={30} />
            <div className={styles.body}>
              <span className={styles.handle}>@{reaction.persona_handle}</span>
              <p className={styles.text}>{reaction.content}</p>
            </div>
          </li>
        ))}
      </ul>

      {last.reactions.length === 0 && (
        <p className={styles.none}>No persona reacted to that post.</p>
      )}

      {last.rejected.length > 0 && (
        <p className={styles.gated}>
          Safety gate blocked {last.rejected.length}{" "}
          {last.rejected.length === 1 ? "reply" : "replies"} ({last.rejected.join(", ")}) —
          still charged, because the model still ran.
        </p>
      )}

      {capNote && <p className={styles.capped}>{capNote}.</p>}

      <dl className={styles.cost}>
        <div>
          <dt>Tokens</dt>
          <dd className="mono">{last.tokens_used.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Cost</dt>
          <dd className="mono">${last.estimated_usd.toFixed(5)}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd className="mono">{last.model_version}</dd>
        </div>
      </dl>
    </div>
  );
}
