// The live pipeline trace: a candidate funnel from per-source generation through
// merge/dedupe and filters down to the selected feed, plus the selected feed's source
// mix and score spread. Counts come from the traced pipeline (foryou.web.trace).

import { useState } from "react";

import { SOURCE_LABELS, type PipelineStageDoc, type PipelineTrace } from "../api/types";
import { fixed, sourceColor } from "./format";
import { Stat } from "./primitives";
import styles from "./PipelinePanel.module.css";

interface Row {
  label: string;
  count: number;
  color: string;
  dim?: boolean;
  step?: boolean;
  selected?: boolean;
}

function buildRows(trace: PipelineTrace): Row[] {
  const rows: Row[] = [];
  for (const source of trace.per_source) {
    rows.push({
      label: SOURCE_LABELS[source.name] ?? source.name,
      count: source.count,
      color: sourceColor(source.name),
      dim: true,
    });
  }
  rows.push({ label: "Merged / deduped", count: trace.merged, color: "var(--border-strong)", step: true });
  for (const filter of trace.filters) {
    rows.push({ label: filter.name, count: filter.count, color: "var(--surface-3)", dim: true });
  }
  rows.push({ label: "Selected feed", count: trace.selected, color: "var(--accent)", selected: true });
  return rows;
}

export function PipelinePanel({
  trace,
  stages,
}: {
  trace: PipelineTrace;
  stages: PipelineStageDoc[];
}) {
  const [showLegend, setShowLegend] = useState(false);
  const rows = buildRows(trace);
  const max = Math.max(trace.candidates_total, 1);

  return (
    <div className={styles.wrap}>
      <div className={styles.funnel}>
        {rows.map((row, i) => (
          <div
            key={`${row.label}-${i}`}
            className={`${styles.row} ${row.selected ? styles.selectedRow : ""}`}
          >
            <span className={`${styles.rowLabel} ${row.dim ? styles.rowLabelDim : ""}`}>
              {row.label}
            </span>
            <span
              className={styles.bar}
              style={{ width: `${(row.count / max) * 100}%`, background: row.color }}
            />
            <span className={styles.count}>{row.count}</span>
          </div>
        ))}
      </div>

      <div>
        <div className={styles.mixHead}>Selected source mix</div>
        <div className={styles.funnel}>
          {trace.source_mix.map((source) => (
            <div key={source.name} className={styles.row}>
              <span className={styles.rowLabel}>{SOURCE_LABELS[source.name] ?? source.name}</span>
              <span
                className={styles.bar}
                style={{
                  width: `${(source.count / Math.max(trace.selected, 1)) * 100}%`,
                  background: sourceColor(source.name),
                }}
              />
              <span className={styles.count}>{source.count}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className={styles.statsHead}>Selected scores</div>
        <div className={styles.stats}>
          <Stat value={fixed(trace.score_stats.min, 2)} label="min" />
          <Stat value={fixed(trace.score_stats.mean, 2)} label="mean" />
          <Stat value={fixed(trace.score_stats.max, 2)} label="max" />
          <Stat value={trace.diversified} label="diversified" />
        </div>
      </div>

      <div className={styles.legend}>
        <button className={styles.legendToggle} onClick={() => setShowLegend((v) => !v)}>
          <span>{showLegend ? "▾" : "▸"}</span> How the pipeline works
        </button>
        {showLegend && (
          <div className={styles.legendList}>
            {stages.map((stage, i) => (
              <div key={stage.key} className={styles.legendItem}>
                <span className={styles.legendNum}>{i + 1}</span>
                <span className={styles.legendText}>
                  <span className={styles.legendTitle}>{stage.title}</span>
                  <span className={styles.legendDesc}>{stage.description}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
