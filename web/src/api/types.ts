// TypeScript mirrors of the FastAPI response schemas (src/foryou/web/schemas.py).

export interface SourceTag {
  source: string;
  score: number;
}

export interface ActionScores {
  like: number;
  reply: number;
  repost: number;
  quote: number;
  dwell: number;
}

export interface Features {
  author_affinity: number;
  topic_match: number;
  recency: number;
  engagement_velocity: number;
  embedding_similarity: number;
}

export interface WhyThisPost {
  sources: SourceTag[];
  action_scores: ActionScores | null;
  features: Features | null;
  preference_multiplier: number | null;
  mmr_penalty: number | null;
  final_score: number | null;
  rank: number | null;
}

export interface Author {
  id: string;
  handle: string;
  display_name: string;
  is_persona: boolean;
  archetype: string | null;
  bio?: string | null;
}

export interface FeedItem {
  post_id: string;
  content: string;
  created_at: string;
  topics: string[];
  like_count: number;
  reply_count: number;
  repost_count: number;
  quote_count: number;
  author: Author;
  rank: number | null;
  final_score: number | null;
  why: WhyThisPost;
}

export interface StageCount {
  name: string;
  count: number;
}

export interface ScoreStats {
  min: number | null;
  max: number | null;
  mean: number | null;
}

export interface PipelineTrace {
  per_source: StageCount[];
  candidates_total: number;
  merged: number;
  filters: StageCount[];
  selected: number;
  source_mix: StageCount[];
  score_stats: ScoreStats;
  diversified: number;
}

export interface FeedResponse {
  request_id: string;
  viewer: Author;
  limit: number;
  model_version: string | null;
  weight_vector: Record<string, number>;
  preferences: Record<string, unknown>;
  trace: PipelineTrace;
  items: FeedItem[];
}

export interface Preferences {
  recency: number;
  friends_global: number;
  niche_viral: number;
  exploration: number | null;
  topic_weights: Record<string, number>;
}

export interface UserSummary {
  id: string;
  handle: string;
  display_name: string;
  is_persona: boolean;
  archetype: string | null;
}

export interface PipelineStageDoc {
  key: string;
  title: string;
  description: string;
}

export interface TrendItem {
  post_id: string;
  content: string;
  author: Author;
  velocity: number;
  topics: string[];
  like_count: number;
  reply_count: number;
  repost_count: number;
  quote_count: number;
}

export const ACTION_KEYS = ["like", "reply", "repost", "quote", "dwell"] as const;
export type ActionKey = (typeof ACTION_KEYS)[number];

export const SOURCE_LABELS: Record<string, string> = {
  in_network: "In-network",
  out_of_network: "Out-of-network",
  trending: "Trending",
};
