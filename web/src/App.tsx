// The ranking inspector — three perspectives over the same live For You pipeline.
// Reader:   the feed as a viewer sees it (no scores) with plain-language controls.
// Analyst:  the ranked feed plus the Preferences / Why / Trace / Trends inspector rail.
// Operator: the bounded live-trigger path (plan.md §8) — write to the world, watch the
//           personas react, and see exactly what it cost against today's hard caps.

import { type ReactNode, useState } from "react";

import styles from "./app/App.module.css";
import { ReaderControls } from "./app/ReaderControls";
import { useFeed } from "./app/useFeed";
import { useOperator } from "./app/useOperator";
import { SOURCE_LABELS } from "./api/types";
import { BudgetMeter } from "./design-system/BudgetMeter";
import { Composer } from "./design-system/Composer";
import { FeedCard } from "./design-system/FeedCard";
import { sourceColor } from "./design-system/format";
import { PipelinePanel } from "./design-system/PipelinePanel";
import { PreferenceRail } from "./design-system/PreferenceRail";
import { ReactionsPanel } from "./design-system/ReactionsPanel";
import { ReaderFeedCard } from "./design-system/ReaderFeedCard";
import { TrendsPanel } from "./design-system/TrendsPanel";
import { WhyThisPostPanel } from "./design-system/WhyThisPostPanel";

const SOURCES = ["in_network", "out_of_network", "trending"];

type View = "reader" | "analyst" | "operator";
const VIEWS: View[] = ["reader", "analyst", "operator"];

function RailSection({
  title,
  meta,
  metaAccent,
  children,
}: {
  title: string;
  meta?: ReactNode;
  metaAccent?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={styles.railSection}>
      <header className={styles.railHead}>
        <span className={styles.railTitle}>{title}</span>
        {meta !== undefined && (
          <span className={`${styles.railMeta} ${metaAccent ? styles.railMetaAccent : ""}`}>
            {meta}
          </span>
        )}
      </header>
      {children}
    </section>
  );
}

export default function App() {
  const ctl = useFeed();
  const { feed } = ctl;
  const op = useOperator(ctl.viewer, ctl.refresh);
  const [view, setView] = useState<View>("analyst");

  const feedCount = feed
    ? `${feed.items.length} ranked · ${ctl.neutral ? "untuned baseline" : "tuned by your preferences"}`
    : "loading…";

  return (
    <div className={styles.app}>
      <header className={styles.masthead}>
        <div className={styles.brand}>
          <span className={styles.brandTitle}>For You</span>
          <span className="lbl">Ranking Inspector</span>
        </div>

        <nav className={styles.nav}>
          {VIEWS.map((name) => (
            <button
              key={name}
              className={`${styles.tab} ${view === name ? styles.tabActive : ""}`}
              onClick={() => setView(name)}
            >
              {name[0]!.toUpperCase() + name.slice(1)}
            </button>
          ))}
        </nav>

        <div className={styles.mastheadMeta}>
          <span className={`mono ${styles.model}`}>model {feed?.model_version ?? "—"}</span>
          <div className={styles.picker}>
            <span className="lbl">Viewing as</span>
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

      {ctl.error && <div className={styles.banner}>{ctl.error}</div>}

      {view === "reader" && (
        <main className={styles.readerMain}>
          <div className={styles.readerColumn}>
            <div className={styles.readerIntro}>
              <span className={styles.readerHeadline}>For you</span>
              <span className={styles.readerSub}>
                The feed @{ctl.viewer ?? "…"} actually sees — no scores, just the result.
              </span>
            </div>

            <ReaderControls state={ctl.prefs} disabled={!ctl.viewer} onChange={ctl.setPrefs} />

            <div className={`${styles.readerList} ${ctl.loading ? styles.dim : ""}`}>
              {feed
                ? feed.items.map((item) => <ReaderFeedCard key={item.post_id} item={item} />)
                : !ctl.error &&
                  Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className={styles.readerSkeleton} />
                  ))}
            </div>
          </div>
        </main>
      )}

      {view === "operator" && (
        <main className={styles.operatorMain}>
          <div className={styles.operatorColumn}>
            <div className={styles.readerIntro}>
              <span className={styles.readerHeadline}>Write to the world</span>
              <span className={styles.readerSub}>
                Posting as @{ctl.viewer ?? "…"} may trigger a few persona replies. Every reply
                is generated, safety-gated in code, and charged against a hard daily cap — the
                world never grows on its own.
              </span>
            </div>

            {op.error && <div className={styles.banner}>{op.error}</div>}

            <RailSection title="Compose" meta={op.react ? "reactions on" : "reactions off"}>
              <Composer
                value={op.draft}
                onChange={op.setDraft}
                onSubmit={() => void op.submit()}
                react={op.react}
                onReactChange={op.setReact}
                viewer={ctl.viewer}
                posting={op.posting}
                exhausted={op.budget?.exhausted}
              />
            </RailSection>

            <RailSection
              title="Reactions"
              meta={op.last ? `${op.last.reactions.length} fired` : undefined}
            >
              <ReactionsPanel last={op.last} />
            </RailSection>
          </div>

          <div className={styles.rail}>
            <RailSection
              title="Budget today"
              meta={op.budget?.exhausted ? "spent" : "bounded"}
              metaAccent={op.budget?.exhausted}
            >
              <BudgetMeter budget={op.budget} />
            </RailSection>

            <RailSection title="Trends" meta="velocity window">
              <TrendsPanel trends={ctl.trends} />
            </RailSection>
          </div>
        </main>
      )}

      {view === "analyst" && (
        <main className={styles.analystMain}>
          {/* Feed */}
          <div className={styles.feedCol}>
            <div className={styles.feedHead}>
              <span className={styles.feedTitle}>Home feed</span>
              <span className={styles.feedSub}>{feedCount}</span>
            </div>
            <div className={styles.legendBar}>
              {SOURCES.map((source) => (
                <span key={source} className={styles.legendChip}>
                  <span className={styles.legendSwatch} style={{ background: sourceColor(source) }} />
                  {SOURCE_LABELS[source]}
                </span>
              ))}
            </div>
            <div className={`${styles.feedList} ${ctl.loading ? styles.dim : ""}`}>
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
                  Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className={styles.feedSkeleton} />
                  ))}
            </div>
          </div>

          {/* Inspector rail */}
          <div className={styles.rail}>
            <RailSection
              title="Preferences"
              meta={ctl.neutral ? "neutral" : "tuned"}
              metaAccent={!ctl.neutral}
            >
              <PreferenceRail
                state={ctl.prefs}
                topics={ctl.topics}
                disabled={!ctl.viewer}
                onChange={ctl.setPrefs}
              />
            </RailSection>

            <RailSection
              title="Why this post?"
              meta={ctl.selected ? `rank ${(ctl.selected.rank ?? 0) + 1}` : undefined}
            >
              <WhyThisPostPanel item={ctl.selected} weightVector={feed?.weight_vector ?? {}} />
            </RailSection>

            {feed && (
              <RailSection title="Pipeline trace" meta={`req ${feed.request_id.slice(0, 8)}`}>
                <PipelinePanel trace={feed.trace} stages={ctl.stages} />
              </RailSection>
            )}

            <RailSection title="Trends" meta="velocity window">
              <TrendsPanel trends={ctl.trends} />
            </RailSection>
          </div>
        </main>
      )}
    </div>
  );
}
