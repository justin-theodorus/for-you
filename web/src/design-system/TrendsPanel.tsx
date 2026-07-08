// Compact trending list, driven by the pipeline's own TrendingSource aggregation.

import type { TrendItem } from "../api/types";
import { compact } from "./format";
import styles from "./TrendsPanel.module.css";

export function TrendsPanel({ trends }: { trends: TrendItem[] }) {
  if (trends.length === 0) {
    return <p className={styles.empty}>No engagement in the trending window.</p>;
  }
  return (
    <div className={styles.list}>
      {trends.map((item) => (
        <div key={item.post_id} className={styles.item}>
          <div className={styles.velocity}>
            <span className={styles.velNum}>{compact(item.velocity)}</span>
            <span className={styles.velLabel}>eng</span>
          </div>
          <div className={styles.body}>
            <span className={styles.text}>{item.content}</span>
            <span className={styles.author}>@{item.author.handle}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
