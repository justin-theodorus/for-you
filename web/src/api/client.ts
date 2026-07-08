// Typed fetch client for the ranking API. Base URL comes from VITE_API_BASE_URL
// (set by the compose `web` service to follow API_PORT); defaults to :8000.

import type {
  FeedResponse,
  PipelineStageDoc,
  Preferences,
  TrendItem,
  UserSummary,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
    throw new ApiError(`Cannot reach the ranking API at ${BASE}. Is \`make api\` running?`, 0);
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
