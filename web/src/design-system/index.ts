// Public barrel for the For You design system — the entry the Claude Design sync bundles.
// Exports the reusable, presentational components (the app-specific composition in
// src/app/ is intentionally not part of the design system).

// Ship the design tokens with the library CSS so components render on-brand when the
// design agent composes them (bundled into dist-lib/style.css via cssCodeSplit: false).
import "./tokens.css";

export { Avatar, Meter, Panel, Pill, SourceBadge, Stat } from "./primitives";
export { ActionScoreBars } from "./ActionScoreBars";
export { BudgetMeter } from "./BudgetMeter";
export { Composer } from "./Composer";
export { FeedCard } from "./FeedCard";
export { ReaderFeedCard } from "./ReaderFeedCard";
export { ReactionsPanel } from "./ReactionsPanel";
export { WhyThisPostPanel } from "./WhyThisPostPanel";
export { PreferenceRail } from "./PreferenceRail";
export { PipelinePanel } from "./PipelinePanel";
export { TrendsPanel } from "./TrendsPanel";
