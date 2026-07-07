"""Stub selector — the seam MMR diversification (plan.md §5) replaces.

Ranks by final score and truncates to the requested feed size. ``mmr_penalty`` is
left unset (diversification is a later component); assigning it here is the extension
point for maximal-marginal-relevance selection.
"""

from __future__ import annotations

from dataclasses import replace

from foryou.candidates.types import Candidate, RankingContext


def _score_key(candidate: Candidate) -> float:
    return candidate.score if candidate.score is not None else float("-inf")


class TopKSelector:
    """Sort by descending score, assign contiguous ranks, keep the top ``limit``."""

    def select(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]:
        ordered = sorted(candidates, key=_score_key, reverse=True)
        top = ordered[: ctx.limit]
        return [replace(candidate, rank=rank) for rank, candidate in enumerate(top)]
