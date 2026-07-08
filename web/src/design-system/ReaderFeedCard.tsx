// One post in the Reader view — the feed as a viewer actually sees it: no scores, serif
// body, plain engagement counts, and an optional plain-language "why am I seeing this?"
// derived from the post's dominant provenance.

import { useState } from "react";

import type { FeedItem } from "../api/types";
import { compact, readerReason, sourceColor } from "./format";
import styles from "./ReaderFeedCard.module.css";
import { Avatar } from "./primitives";

export function ReaderFeedCard({ item }: { item: FeedItem }) {
  const [expanded, setExpanded] = useState(false);
  const reason = readerReason(item);

  return (
    <article className={styles.card}>
      <div className={styles.head}>
        <Avatar handle={item.author.handle} name={item.author.display_name} size={38} />
        <div className={styles.names}>
          <span className={styles.displayName}>{item.author.display_name}</span>
          <span className={styles.handle}>
            @{item.author.handle}
            {item.author.archetype ? ` · ${item.author.archetype}` : ""}
          </span>
        </div>
      </div>

      <p className={styles.content}>{item.content}</p>

      <div className={styles.footer}>
        <span>{compact(item.like_count)} likes</span>
        <span>{compact(item.repost_count)} reposts</span>
        <span>{compact(item.reply_count)} replies</span>
        <button className={styles.whyLink} onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Hide reason" : "Why am I seeing this?"}
        </button>
      </div>

      {expanded && (
        <div className={styles.reason}>
          <div className={styles.reasonHead}>
            <span
              className={styles.reasonDot}
              style={{ background: sourceColor(reason.primarySource) }}
            />
            <span className={`lbl ${styles.reasonLabel}`}>{reason.label}</span>
          </div>
          <p className={styles.reasonText}>{reason.sentence}</p>
        </div>
      )}
    </article>
  );
}
