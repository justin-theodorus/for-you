// The ranking inspector — a three-zone control room over the live For You pipeline.
// Left: the §4 preference controls + trends. Center: the ranked feed. Right: the
// "Why this post?" explainability panel + the live pipeline trace.

import styles from "./app/App.module.css";
import { useFeed } from "./app/useFeed";
import { SOURCE_LABELS } from "./api/types";
import { FeedCard } from "./design-system/FeedCard";
import { PipelinePanel } from "./design-system/PipelinePanel";
import { PreferenceRail } from "./design-system/PreferenceRail";
import { Panel } from "./design-system/primitives";
import { sourceColor } from "./design-system/format";
import { TrendsPanel } from "./design-system/TrendsPanel";
import { WhyThisPostPanel } from "./design-system/WhyThisPostPanel";

const SOURCES = ["in_network", "out_of_network", "trending"];

export default function App() {
  const ctl = useFeed();
  const { feed } = ctl;

  return (
    <div className={styles.app}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>Fy</span>
          <span className={styles.brandText}>
            <span className={styles.brandTitle}>For You — Ranking Inspector</span>
            <span className={styles.brandSub}>a tunable, explainable recommendation pipeline</span>
          </span>
        </div>

        <div className={styles.topMeta}>
          <div className={styles.legendBar}>
            {SOURCES.map((source) => (
              <span key={source} className={styles.legendChip}>
                <span className={styles.legendSwatch} style={{ background: sourceColor(source) }} />
                {SOURCE_LABELS[source]}
              </span>
            ))}
          </div>
          {feed?.model_version && (
            <span className={styles.chip}>
              <span className={styles.chipDot} /> model {feed.model_version}
            </span>
          )}
          <span className={`${styles.chip} ${ctl.loading ? styles.chipLoading : ""}`}>
            <span className={styles.chipDot} /> {ctl.loading ? "ranking…" : "live"}
          </span>
          <div className={styles.picker}>
            <span className={styles.pickerLabel}>Viewer</span>
            <select
              className={styles.select}
              value={ctl.viewer ?? ""}
              onChange={(event) => ctl.setViewer(event.target.value)}
            >
              {ctl.users.map((user) => (
                <option key={user.id} value={user.handle}>
                  @{user.handle}
                  {user.is_persona ? ` · ${user.archetype ?? "persona"}` : " · reader"}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      <main className={styles.main}>
        {/* Left — controls */}
        <div className={`${styles.col} ${styles.colLeft}`}>
          <Panel title="Preferences" accent="var(--accent)" meta={ctl.neutral ? "neutral" : "tuned"}>
            <PreferenceRail
              state={ctl.prefs}
              topics={ctl.topics}
              disabled={!ctl.viewer}
              onChange={ctl.setPrefs}
            />
          </Panel>
          <Panel title="Trends" accent="var(--src-trending)">
            <TrendsPanel trends={ctl.trends} />
          </Panel>
        </div>

        {/* Center — feed */}
        <div className={`${styles.col} ${styles.colCenter}`}>
          <div className={styles.feedHead}>
            <span className={styles.feedTitle}>Home feed</span>
            <span className={styles.feedSub}>
              {feed
                ? `${feed.items.length} ranked · ${
                    ctl.neutral ? "untuned baseline" : "tuned by your preferences"
                  }`
                : "loading…"}
            </span>
          </div>

          {ctl.error && <div className={styles.banner}>{ctl.error}</div>}

          <div className={`${styles.feedList} ${ctl.loading ? styles.feedListLoading : ""}`}>
            {feed
              ? feed.items.map((item) => (
                  <FeedCard
                    key={item.post_id}
                    item={item}
                    selected={ctl.selected?.post_id === item.post_id}
                    onSelect={ctl.setSelected}
                  />
                ))
              : !ctl.error &&
                Array.from({ length: 5 }).map((_, i) => <div key={i} className={styles.skeleton} />)}
          </div>
        </div>

        {/* Right — inspector */}
        <div className={`${styles.col} ${styles.colRight}`}>
          <Panel
            title="Why this post?"
            meta={ctl.selected ? `rank ${(ctl.selected.rank ?? 0) + 1}` : undefined}
          >
            <WhyThisPostPanel item={ctl.selected} weightVector={feed?.weight_vector ?? {}} />
          </Panel>
          {feed && (
            <Panel title="Pipeline trace" accent="var(--src-out-of-network)" meta={`req ${feed.request_id.slice(0, 8)}`}>
              <PipelinePanel trace={feed.trace} stages={ctl.stages} />
            </Panel>
          )}
        </div>
      </main>
    </div>
  );
}
