// Orchestrates the demo: loads static data once, then debounces preference/viewer
// changes into live re-rank requests. Stale responses are dropped so the newest slider
// position always wins.

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchFeed, fetchPipeline, fetchTopics, fetchTrends, fetchUsers } from "../api/client";
import type {
  FeedItem,
  FeedResponse,
  PipelineStageDoc,
  TrendItem,
  UserSummary,
} from "../api/types";
import { isNeutral, NEUTRAL_PREFS, type PreferenceState, toPayload } from "./preferences";

const DEBOUNCE_MS = 250;
const FEED_LIMIT = 20;

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong talking to the ranking API.";
}

export interface FeedController {
  users: UserSummary[];
  topics: string[];
  stages: PipelineStageDoc[];
  trends: TrendItem[];
  viewer: string | null;
  setViewer: (handle: string) => void;
  prefs: PreferenceState;
  setPrefs: (next: PreferenceState) => void;
  feed: FeedResponse | null;
  loading: boolean;
  error: string | null;
  selected: FeedItem | null;
  setSelected: (item: FeedItem | null) => void;
  neutral: boolean;
  /** Re-rank and re-read trends. The world only changes when someone writes to it —
   *  publishing a post (plan.md §8) is the one thing that does. */
  refresh: () => Promise<void>;
}

export function useFeed(): FeedController {
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [topics, setTopics] = useState<string[]>([]);
  const [stages, setStages] = useState<PipelineStageDoc[]>([]);
  const [trends, setTrends] = useState<TrendItem[]>([]);
  const [viewer, setViewer] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<PreferenceState>(NEUTRAL_PREFS);
  const [feed, setFeed] = useState<FeedResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const reqIdRef = useRef(0);

  // Static data + default viewer, once.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const [loadedUsers, loadedTopics, loadedStages] = await Promise.all([
          fetchUsers(),
          fetchTopics(),
          fetchPipeline(),
        ]);
        if (!alive) return;
        setUsers(loadedUsers);
        setTopics(loadedTopics);
        setStages(loadedStages);
        const firstReader = loadedUsers.find((user) => !user.is_persona) ?? loadedUsers[0];
        if (firstReader) setViewer(firstReader.handle);
      } catch (caught) {
        if (alive) setError(errorMessage(caught));
      }
      try {
        const loadedTrends = await fetchTrends();
        if (alive) setTrends(loadedTrends);
      } catch {
        // Trends are a nice-to-have; ignore failures.
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const runFeed = useCallback(async (handle: string, state: PreferenceState) => {
    const id = (reqIdRef.current += 1);
    setLoading(true);
    setError(null);
    try {
      const payload = isNeutral(state) ? null : toPayload(state);
      const data = await fetchFeed(handle, payload, FEED_LIMIT);
      if (id === reqIdRef.current) setFeed(data);
    } catch (caught) {
      if (id === reqIdRef.current) setError(errorMessage(caught));
    } finally {
      if (id === reqIdRef.current) setLoading(false);
    }
  }, []);

  // Debounced re-rank whenever the viewer or a preference changes.
  useEffect(() => {
    if (!viewer) return;
    const timer = window.setTimeout(() => void runFeed(viewer, prefs), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [viewer, prefs, runFeed]);

  const selected =
    feed && selectedId
      ? (feed.items.find((item) => item.post_id === selectedId) ?? null)
      : null;

  const setSelected = useCallback((item: FeedItem | null) => {
    setSelectedId(item?.post_id ?? null);
  }, []);

  // Re-rank against the mutated world after a write, and pull fresh trends: a live post's
  // reactions add engagement, which moves the velocity window.
  const refresh = useCallback(async () => {
    if (!viewer) return;
    await runFeed(viewer, prefs);
    try {
      setTrends(await fetchTrends());
    } catch {
      // Trends are a nice-to-have; a stale panel shouldn't surface an error.
    }
  }, [viewer, prefs, runFeed]);

  return {
    users,
    topics,
    stages,
    trends,
    viewer,
    setViewer,
    prefs,
    setPrefs,
    feed,
    loading,
    error,
    selected,
    setSelected,
    neutral: isNeutral(prefs),
    refresh,
  };
}
