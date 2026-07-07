"""Selection stage — turns scored candidates into the ranked feed.

Two selectors share the ``Selector`` protocol (sync, pure, no DB):

* :class:`TopKSelector` — the trivial relevance baseline (descending score, truncate).
* :class:`MMRSelector` — maximal marginal relevance (plan.md §5): trades relevance for
  dissimilarity from the already-selected feed, the primary anti-filter-bubble mechanism.

``MMRSelector`` fills the pre-reserved ``Candidate.mmr_penalty`` field, which the
impression logger persists for the "Why this post?" panel.
"""

from __future__ import annotations

from dataclasses import replace

from foryou.candidates.hydrator import cosine_similarity
from foryou.candidates.types import Candidate, RankingContext
from foryou.config import settings


def _score_key(candidate: Candidate) -> float:
    return candidate.score if candidate.score is not None else float("-inf")


class TopKSelector:
    """Sort by descending score, assign contiguous ranks, keep the top ``limit``."""

    def select(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]:
        ordered = sorted(candidates, key=_score_key, reverse=True)
        top = ordered[: ctx.limit]
        return [replace(candidate, rank=rank) for rank, candidate in enumerate(top)]


def _normalize_relevance(candidates: list[Candidate]) -> list[float]:
    """Min-max the pool's scores to [0, 1] so they mix meaningfully with cosine.

    Scores (weighted sums of sigmoids) and cosine similarity live on different scales;
    without this rescale the ``lambda`` mix is meaningless. Missing scores floor to 0.0.
    A zero-span pool (all-equal or single candidate) carries no relevance signal, so
    every candidate maps to 1.0 and selection is driven purely by the diversity term.
    """
    scores = [c.score if c.score is not None else 0.0 for c in candidates]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    if span <= 0.0:
        return [1.0] * len(candidates)
    return [(score - lo) / span for score in scores]


class MMRSelector:
    """Greedy maximal marginal relevance.

    Each pick maximizes ``lambda * relevance - (1 - lambda) * max_similarity_to_selected``.
    ``lambda`` (relevance weight, in [0, 1]) is the exploration knob: 1.0 reproduces
    :class:`TopKSelector`; lower values diversify harder. A per-request ``ctx.mmr_lambda``
    overrides the configured default (the plan.md §4 preference-slider seam).

    Candidates without an embedding are never penalized — ``cosine_similarity`` returns
    0.0 for a missing vector, so an uncomparable post is treated as maximally diverse and
    competes on pure relevance. This is deliberate: we don't suppress what we can't compare.
    """

    def __init__(self, *, lambda_relevance: float = settings.mmr_lambda) -> None:
        self._lambda = lambda_relevance

    def select(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]:
        if not candidates:
            return []

        # plan.md §4 seam: a per-request lambda (from the preference slider) wins over the
        # constructor/settings default.
        lam = ctx.mmr_lambda if ctx.mmr_lambda is not None else self._lambda
        relevance = _normalize_relevance(candidates)

        remaining = list(range(len(candidates)))
        selected: list[int] = []
        penalties: list[float] = []

        for _ in range(min(ctx.limit, len(candidates))):
            best_index = -1
            best_mmr = float("-inf")
            best_penalty = 0.0
            for i in remaining:
                # O(k^2 * n * d): recomputes similarity against the whole selected set each
                # step. Fine for hundreds of candidates; an incremental cached max-sim would
                # cut it to O(k * n * d) if profiling ever demands it.
                max_sim = max(
                    (cosine_similarity(candidates[i].embedding, candidates[s].embedding)
                     for s in selected),
                    default=0.0,
                )
                penalty = (1.0 - lam) * max_sim
                mmr = lam * relevance[i] - penalty
                if mmr > best_mmr:  # strict '>' -> first-seen (highest score) wins ties
                    best_mmr = mmr
                    best_index = i
                    best_penalty = penalty
            selected.append(best_index)
            penalties.append(best_penalty)
            remaining.remove(best_index)

        return [
            replace(candidates[index], rank=rank, mmr_penalty=penalty)
            for rank, (index, penalty) in enumerate(zip(selected, penalties, strict=True))
        ]
