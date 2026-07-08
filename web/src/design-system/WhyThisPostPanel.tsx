// The "Why this post?" explainability panel — renders the logged impression data for the
// selected feed item and narrates the score composition end to end. No inference here; all
// of this is exactly what the pipeline computed and feed_impressions persisted.

import { ACTION_KEYS, type FeedItem } from "../api/types";
import { ActionScoreBars } from "./ActionScoreBars";
import { actionColor, fixed } from "./format";
import styles from "./WhyThisPostPanel.module.css";
import { Avatar, Meter, SourceBadge } from "./primitives";

interface WhyThisPostPanelProps {
  item: FeedItem | null;
  weightVector: Record<string, number>;
}

// Feature values that are already in [0,1] read as a fraction directly; engagement
// velocity is a log-count that can exceed 1, so clamp its bar without faking the number.
const UNIT_FEATURES = new Set(["author_affinity", "topic_match", "recency", "embedding_similarity"]);

export function WhyThisPostPanel({ item, weightVector }: WhyThisPostPanelProps) {
  const scores = item?.why.action_scores ?? null;
  if (!item || !scores) {
    return (
      <div className={styles.empty}>
        <span className={styles.emptyIcon}>◎</span>
        <span>Select a post to trace exactly why the engine ranked it there.</span>
      </div>
    );
  }

  const { why } = item;
  const collapse = ACTION_KEYS.reduce((sum, key) => sum + scores[key] * (weightVector[key] ?? 1), 0);
  const mult = why.preference_multiplier ?? 1;
  const penalty = why.mmr_penalty ?? 0;

  return (
    <div className={styles.wrap}>
      <div className={styles.postPeek}>
        <div className={styles.postPeekHead}>
          <Avatar handle={item.author.handle} size={22} />
          <strong>{item.author.display_name}</strong>
          <span className={styles.postPeekHandle}>@{item.author.handle}</span>
        </div>
        <p className={styles.postPeekText}>{item.content}</p>
      </div>

      <div className={styles.section}>
        <span className={styles.sectionTitle}>Surfaced by</span>
        <div className={styles.badges}>
          {why.sources.map((tag) => (
            <SourceBadge key={tag.source} source={tag.source} score={tag.score} />
          ))}
        </div>
        <span className={styles.hint}>
          Raw within-source signal: recency decay, cosine similarity, or engagement count.
        </span>
      </div>

      <div className={styles.section}>
        <span className={styles.sectionTitle}>Features</span>
        {why.features &&
          Object.entries(why.features).map(([name, value]) => (
            <Meter
              key={name}
              label={name.replace(/_/g, " ")}
              value={value}
              fraction={UNIT_FEATURES.has(name) ? value : Math.tanh(value)}
              display={fixed(value, 2)}
            />
          ))}
      </div>

      <div className={styles.section}>
        <span className={styles.sectionTitle}>Predicted action probabilities</span>
        <ActionScoreBars scores={scores} />
        <span className={styles.hint}>
          Weight vector:{" "}
          {ACTION_KEYS.map((key, i) => (
            <span key={key} className="mono" style={{ color: actionColor(key) }}>
              {key} ×{fixed(weightVector[key] ?? 1, 1)}
              {i < ACTION_KEYS.length - 1 ? "  " : ""}
            </span>
          ))}
        </span>
      </div>

      <div className={styles.section}>
        <span className={styles.sectionTitle}>Score composition</span>
        <div className={styles.formula}>
          <div className={styles.formulaRow}>
            <span>Model score (Σ weight · action)</span>
            <span className={styles.formulaVal}>{fixed(collapse, 3)}</span>
          </div>
          <div className={styles.formulaRow}>
            <span>× preference multiplier (§4)</span>
            <span className={styles.formulaVal}>×{fixed(mult, 2)}</span>
          </div>
          <div className={`${styles.formulaRow} ${styles.formulaFinal}`}>
            <span>Final score</span>
            <span className={styles.formulaVal}>{fixed(why.final_score, 3)}</span>
          </div>
        </div>
        <div className={styles.formula}>
          <div className={styles.formulaRow}>
            <span>MMR diversity penalty (§5)</span>
            <span className={`${styles.formulaVal} ${penalty > 0 ? styles.penalty : ""}`}>
              {penalty > 0 ? `−${fixed(penalty, 3)}` : "0.000"}
            </span>
          </div>
        </div>
        <span className={styles.hint}>
          The penalty shaped this post's <em>position</em> during greedy MMR selection —
          higher when it looked like posts already placed above it.
        </span>
      </div>
    </div>
  );
}
