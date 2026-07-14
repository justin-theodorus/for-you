// Operator state: compose a post, trigger bounded persona reactions, watch the budget
// (plan.md §8). The only place in the app that *writes* to the world — so it's also the
// only place that has to invalidate the feed and trends afterwards.

import { useCallback, useEffect, useState } from "react";

import { ApiError, createPost, fetchBudget } from "../api/client";
import type { BudgetStatus, LivePostResponse } from "../api/types";

export interface OperatorController {
  draft: string;
  setDraft: (next: string) => void;
  react: boolean;
  setReact: (next: boolean) => void;
  budget: BudgetStatus | null;
  last: LivePostResponse | null;
  posting: boolean;
  error: string | null;
  submit: () => Promise<void>;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong publishing that post.";
}

/**
 * @param viewer  the handle the post is authored as (the app's "Viewing as" selection)
 * @param onWorldChanged  re-rank the feed once the world has actually changed
 */
export function useOperator(
  viewer: string | null,
  onWorldChanged: () => Promise<void>,
): OperatorController {
  const [draft, setDraft] = useState("");
  const [react, setReact] = useState(true);
  const [budget, setBudget] = useState<BudgetStatus | null>(null);
  const [last, setLast] = useState<LivePostResponse | null>(null);
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The budget is a *daily* counter, so it's meaningful before the first post too.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const loaded = await fetchBudget();
        if (alive) setBudget(loaded);
      } catch {
        // A missing budget just leaves the meter blank; it isn't worth a banner.
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const submit = useCallback(async () => {
    const content = draft.trim();
    if (!viewer || !content || posting) return;
    setPosting(true);
    setError(null);
    try {
      const response = await createPost({
        handle: viewer,
        content,
        trigger_reactions: react,
      });
      setLast(response);
      setBudget(response.budget);
      setDraft("");
      // The post and its replies are already embedded server-side, so a re-rank sees them.
      await onWorldChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPosting(false);
    }
  }, [draft, viewer, react, posting, onWorldChanged]);

  return {
    draft,
    setDraft,
    react,
    setReact,
    budget,
    last,
    posting,
    error,
    submit,
  };
}
