// One ranked post. Shows its rank + final score, author, content, source provenance,
// and the preference multiplier — the at-a-glance "why". Click to pin the full
// explainability panel in the inspector.

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
  const showMult = mult !== null && Math.abs(mult - 1) > 0.001;
  return (
    <article
      className={`${styles.card} ${selected ? styles.selected : ""}`}
      onClick={() => onSelect(item)}
    >
      <div className={styles.rank}>
        <span className={styles.rankNum}>{(item.rank ?? 0) + 1}</span>
        <span className={styles.rankScore}>{fixed(item.final_score, 2)}</span>
      </div>

      <div className={styles.body}>
        <div className={styles.head}>
          <Avatar handle={item.author.handle} size={34} />
          <div className={styles.names}>
            <span className={styles.displayName}>{item.author.display_name}</span>
            <span className={styles.handle}>@{item.author.handle}</span>
          </div>
          {item.author.archetype && <span className={styles.persona}>{item.author.archetype}</span>}
        </div>

        <p className={styles.content}>{item.content}</p>

        {item.topics.length > 0 && (
          <div className={styles.topics}>
            {item.topics.map((topic) => (
              <span key={topic} className={styles.topic}>
                #{topic}
              </span>
            ))}
          </div>
        )}

        <div className={styles.footer}>
          <div className={styles.badges}>
            {item.why.sources.map((tag) => (
              <SourceBadge key={tag.source} source={tag.source} score={tag.score} />
            ))}
          </div>
          {showMult && (
            <span className={`${styles.mult} ${mult! >= 1 ? styles.multUp : styles.multDown}`}>
              pref ×{fixed(mult, 2)}
            </span>
          )}
          <div className={styles.counters}>
            <span>♥ {compact(item.like_count)}</span>
            <span>↺ {compact(item.repost_count)}</span>
            <span>↩ {compact(item.reply_count)}</span>
          </div>
        </div>
      </div>
    </article>
  );
}
