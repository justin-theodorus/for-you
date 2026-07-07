"""Stub scorer — the seam the trained model (plan.md §3) replaces.

Turns :class:`Features` into per-action probabilities via fixed logistic combinations,
then collapses them to one score as a weighted sum over the request's weight vector
(the preference-layer seam, plan.md §4). Pure and DB-free by design.
"""

from __future__ import annotations

import math
from dataclasses import replace

from foryou.candidates.types import ActionScores, Candidate, RankingContext


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class HeuristicScorer:
    """Deterministic feature-combination scorer (placeholder for a trained model)."""

    def score(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]:
        return [self._score_one(candidate, ctx) for candidate in candidates]

    def _score_one(self, candidate: Candidate, ctx: RankingContext) -> Candidate:
        features = candidate.features
        if features is None:
            raise ValueError("candidate must be hydrated before scoring")

        actions = ActionScores(
            like=_sigmoid(
                1.2 * features.author_affinity
                + 1.0 * features.topic_match
                + 0.8 * features.embedding_similarity
            ),
            reply=_sigmoid(1.5 * features.author_affinity + 0.5 * features.topic_match),
            repost=_sigmoid(0.6 * features.engagement_velocity + 0.8 * features.topic_match),
            quote=_sigmoid(0.9 * features.topic_match + 0.3 * features.author_affinity),
            dwell=_sigmoid(1.0 * features.recency + 0.7 * features.embedding_similarity),
        )
        total = sum(
            ctx.weight_vector.get(action, 0.0) * probability
            for action, probability in actions.as_dict().items()
        )
        return replace(candidate, action_scores=actions, score=total)
