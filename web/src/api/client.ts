// Typed fetch client for the ranking API. Base URL comes from VITE_API_BASE_URL
// (set by the compose `web` service to follow API_PORT); defaults to :8000.
//
// In production the API serves this bundle itself, so the Docker build sets
// VITE_API_BASE_URL to the empty string. "" is not nullish, so `??` does not fire and every
// request goes out same-origin and relative.

import type {
  AppConfig,
  BudgetStatus,
  FeedResponse,
  LivePostResponse,
  OperatorStatus,
  PipelineStageDoc,
  PostCreateRequest,
  Preferences,
  TrendItem,
  UserSummary,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Header carrying the Operator write secret; mirrors foryou.web.auth.OPERATOR_HEADER. */
const OPERATOR_HEADER = "X-Operator-Secret";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { "content-type": "application/json" },
      ...init,
    });
  } catch (cause) {
    // BASE is "" in production (same-origin), where "is make api running" would be nonsense.
    const where = BASE ? ` at ${BASE}` : "";
    const hint = BASE ? " Is `make api` running?" : " The server may be starting up.";
    throw new ApiError(`Cannot reach the ranking API${where}.${hint}`, 0);
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    const message =
      (detail && typeof detail.detail === "string" && detail.detail) ||
      `Request to ${path} failed (${response.status})`;
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

export function fetchFeed(
  handle: string,
  preferences: Preferences | null,
  limit = 20,
): Promise<FeedResponse> {
  return request<FeedResponse>("/api/feed", {
    method: "POST",
    body: JSON.stringify({ handle, limit, preferences }),
  });
}

export function fetchUsers(): Promise<UserSummary[]> {
  return request<UserSummary[]>("/api/users");
}

export function fetchTopics(): Promise<string[]> {
  return request<string[]>("/api/topics");
}

export function fetchPipeline(): Promise<PipelineStageDoc[]> {
  return request<PipelineStageDoc[]>("/api/pipeline");
}

export function fetchTrends(): Promise<TrendItem[]> {
  return request<TrendItem[]>("/api/trends");
}

export function fetchConfig(): Promise<AppConfig> {
  return request<AppConfig>("/api/config");
}

// --- Live-trigger path (plan.md §8) ---

/** The operator secret as a header, or nothing. `request` stays dumb: no module state. */
function operatorHeaders(secret?: string | null): HeadersInit | undefined {
  return secret ? { [OPERATOR_HEADER]: secret } : undefined;
}

/**
 * Publish a post; the server may trigger a few budget-capped persona reactions.
 * Throws ApiError(401) when the deployment gates writes and the secret is missing or wrong.
 */
export function createPost(
  body: PostCreateRequest,
  secret?: string | null,
): Promise<LivePostResponse> {
  return request<LivePostResponse>("/api/posts", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "content-type": "application/json", ...operatorHeaders(secret) },
  });
}

/** Validate a secret on its own, so a wrong one doesn't cost a post to discover. */
export function unlockOperator(secret: string): Promise<OperatorStatus> {
  return request<OperatorStatus>("/api/operator", { headers: operatorHeaders(secret) });
}

export function fetchBudget(): Promise<BudgetStatus> {
  return request<BudgetStatus>("/api/budget");
}
