// Operator state: compose a post, trigger bounded persona reactions, watch the budget
// (plan.md §8). The only place in the app that *writes* to the world — so it's also the
// only place that has to invalidate the feed and trends afterwards, and the only place
// that carries the write secret on a gated deployment.

import { useCallback, useEffect, useState } from "react";

import { ApiError, createPost, fetchBudget, fetchConfig, unlockOperator } from "../api/client";
import type { BudgetStatus, LivePostResponse } from "../api/types";

// sessionStorage, not localStorage: this is a shared demo password, and it has no business
// outliving the tab it was typed into.
const SECRET_KEY = "foryou.operator.secret";

export interface OperatorController {
  draft: string;
  setDraft: (next: string) => void;
  react: boolean;
  setReact: (next: boolean) => void;
  budget: BudgetStatus | null;
  last: LivePostResponse | null;
  posting: boolean;
  error: string | null;
  /** Does this deployment gate writes at all? Unset secret server-side -> never locked. */
  required: boolean;
  locked: boolean;
  unlocking: boolean;
  unlockError: string | null;
  unlock: (secret: string) => Promise<void>;
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

  const [required, setRequired] = useState(false);
  const [secret, setSecret] = useState<string | null>(() =>
    sessionStorage.getItem(SECRET_KEY),
  );
  const [unlocked, setUnlocked] = useState(false);
  const [unlocking, setUnlocking] = useState(false);
  const [unlockError, setUnlockError] = useState<string | null>(null);

  const relock = useCallback(() => {
    sessionStorage.removeItem(SECRET_KEY);
    setSecret(null);
    setUnlocked(false);
  }, []);

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

  // Ask the server whether writes are gated, and revalidate any secret this tab remembers.
  // A stored value can be stale (rotated secret, different deployment), so it is never
  // trusted on sight — only /api/operator's answer unlocks the composer.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const config = await fetchConfig();
        if (!alive) return;
        setRequired(config.operator_required);
        if (!config.operator_required) return;

        const stored = sessionStorage.getItem(SECRET_KEY);
        if (!stored) return;
        try {
          await unlockOperator(stored);
          if (alive) setUnlocked(true);
        } catch {
          if (alive) relock();
        }
      } catch {
        // Config is unreachable; the composer stays locked only if the server says so.
      }
    })();
    return () => {
      alive = false;
    };
  }, [relock]);

  const unlock = useCallback(async (candidate: string) => {
    const trimmed = candidate.trim();
    if (!trimmed) return;
    setUnlocking(true);
    setUnlockError(null);
    try {
      await unlockOperator(trimmed);
      sessionStorage.setItem(SECRET_KEY, trimmed);
      setSecret(trimmed);
      setUnlocked(true);
    } catch (caught) {
      setUnlockError(
        caught instanceof ApiError && caught.status === 401
          ? "That secret isn't right."
          : "Couldn't check that secret. Try again.",
      );
    } finally {
      setUnlocking(false);
    }
  }, []);

  const submit = useCallback(async () => {
    const content = draft.trim();
    if (!viewer || !content || posting) return;
    setPosting(true);
    setError(null);
    try {
      const response = await createPost(
        { handle: viewer, content, trigger_reactions: react },
        secret,
      );
      setLast(response);
      setBudget(response.budget);
      setDraft("");
      // The post and its replies are already embedded server-side, so a re-rank sees them.
      await onWorldChanged();
    } catch (caught) {
      // The secret was rotated (or revoked) mid-session: drop it and show the lock again
      // rather than letting the composer keep failing.
      if (caught instanceof ApiError && caught.status === 401) {
        relock();
        setUnlockError("That secret is no longer valid — unlock again.");
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setPosting(false);
    }
  }, [draft, viewer, react, posting, secret, onWorldChanged, relock]);

  return {
    draft,
    setDraft,
    react,
    setReact,
    budget,
    last,
    posting,
    error,
    required,
    locked: required && !unlocked,
    unlocking,
    unlockError,
    unlock,
    submit,
  };
}
