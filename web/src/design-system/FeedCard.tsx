// One ranked post in the Analyst feed. Shows its rank + final score, author, content,
// source provenance with per-source score, and the preference multiplier — the at-a-glance
// "why". Click to pin the full explainability panel in the inspector rail.

import type { FeedItem } from "../api/types";
import { compact, fixed } from "./format";
import styles from "./FeedCard.module.css";
import { Avatar, SourceBadge } from "./primitives";

interface FeedCardProps {
  item: FeedItem;
  selected: boolean;
  onSelect: (item: FeedItem) => void;
}

export function FeedCard({ item, selected, onSelect }: FeedCardProps) {
  const mult = item.why.preference_multiplier;
  const showMult = mult !== null && Math.abs(mult - 1) > 0.02;
  return (
    <article
      className={`${styles.card} ${selected ? styles.selected : ""}`}
      onClick={() => onSelect(item)}
    >
      <span className={styles.rank}>{(item.rank ?? 0) + 1}</span>

      <div className={styles.body}>
        <div className={styles.head}>
          <Avatar handle={item.author.handle} name={item.author.display_name} size={30} />
          <div className={styles.names}>
            <span className={styles.displayName}>{item.author.display_name}</span>
            <span className={styles.handle}>
              @{item.author.handle}
              {item.author.archetype ? ` · ${item.author.archetype}` : ""}
            </span>
          </div>
          <div className={styles.score}>
            <span className={`mono ${styles.scoreNum}`}>{fixed(item.final_score, 2)}</span>
            <span className={`lbl ${styles.scoreLabel}`}>score</span>
          </div>
        </div>

        <p className={styles.content}>{item.content}</p>

        <div className={styles.footer}>
          {item.why.sources.map((tag) => (
            <SourceBadge key={tag.source} source={tag.source} score={tag.score} />
          ))}
          {showMult && (
            <span className={`mono ${styles.mult} ${mult! >= 1 ? styles.multUp : styles.multDown}`}>
              pref ×{fixed(mult, 2)}
            </span>
          )}
          <span className={styles.counters}>
            {compact(item.like_count)} · {compact(item.repost_count)} · {compact(item.reply_count)}
          </span>
        </div>
      </div>
    </article>
  );
}
