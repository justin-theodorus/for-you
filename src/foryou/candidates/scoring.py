"""Scorers: features -> per-action probabilities -> one final score.

Two implementations share the seam. :class:`HeuristicScorer` is the dependency-free
placeholder (fixed logistic combinations). :class:`TrainedScorer` (plan.md §3) loads a
trained artifact and predicts — pure Python at request time, no sklearn. Both end in the
shared :func:`_finalize`: :func:`collapse_score` (the weighted sum over the request's
weight vector) times :func:`preference_multiplier` (the plan.md §4 preference overlay).
A neutral request leaves the multiplier at 1.0, so the score is unchanged.

``default_scorer`` picks the trained model when its artifact exists and otherwise falls
back to the heuristic with a warning, so the feed ranks even before a model is trained.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from foryou.candidates.hydrator import cosine_similarity
from foryou.candidates.protocols import Scorer
from foryou.candidates.types import ActionScores, Candidate, RankingContext
from foryou.config import settings
from foryou.scoring.model import ScoringModel, features_to_vector

logger = logging.getLogger(__name__)

HEURISTIC_MODEL_VERSION = "heuristic"

# Softens the (unbounded) log1p engagement-velocity feature into a bounded tanh factor so
# the niche/viral multiplier stays in a sane range; ~log1p of 20 engagements.
VELOCITY_SCALE = 3.0
# Peak topic boost/penalty at cosine = +/-1 (multiplier in [1 - TOPIC_STRENGTH, 1 + ...]).
TOPIC_STRENGTH = 0.5


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def collapse_score(actions: ActionScores, weight_vector: Mapping[str, float]) -> float:
    """Weighted sum of per-action probabilities — the single collapse both scorers use."""
    return sum(
        weight_vector.get(action, 0.0) * probability
        for action, probability in actions.as_dict().items()
    )


def preference_multiplier(candidate: Candidate, ctx: RankingContext) -> float:
    """Post-scoring preference overlay (plan.md §4); 1.0 when the request is neutral.

    Combines the friends/global source mix, the niche/viral velocity bias, and the topic
    sliders into one multiplicative factor on the model score. Each term is skipped when
    its knob is a no-op, so a neutral context returns exactly 1.0 and leaves the score
    untouched (keeping the §3 model valid with no retrain).
    """
    features = candidate.features
    assert features is not None  # scorer runs after hydration
    multiplier = 1.0
    if ctx.source_weights:
        # A candidate merged from several sources keeps every SourceTag; the strongest
        # surfacing reason wins.
        multiplier *= max(
            ctx.source_weights.get(tag.source, 1.0) for tag in candidate.sources
        )
    if ctx.velocity_bias:
        multiplier *= 1.0 + ctx.velocity_bias * math.tanh(
            features.engagement_velocity / VELOCITY_SCALE
        )
    if ctx.topic_query_vector is not None:
        multiplier *= 1.0 + TOPIC_STRENGTH * cosine_similarity(
            candidate.embedding, ctx.topic_query_vector
        )
    return max(0.0, multiplier)


def _require_features(candidate: Candidate) -> None:
    if candidate.features is None:
        raise ValueError("candidate must be hydrated before scoring")


def _finalize(candidate: Candidate, actions: ActionScores, ctx: RankingContext) -> Candidate:
    """Collapse to one score, apply the preference overlay, and record both — the single
    score-producing site shared by both scorers."""
    multiplier = preference_multiplier(candidate, ctx)
    score = collapse_score(actions, ctx.weight_vector) * multiplier
    return replace(
        candidate, action_scores=actions, score=score, preference_multiplier=multiplier
    )


class HeuristicScorer:
    """Deterministic feature-combination scorer (placeholder for a trained model)."""

    model_version = HEURISTIC_MODEL_VERSION

    def score(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]:
        return [self._score_one(candidate, ctx) for candidate in candidates]

    def _score_one(self, candidate: Candidate, ctx: RankingContext) -> Candidate:
        _require_features(candidate)
        features = candidate.features
        assert features is not None

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
        return _finalize(candidate, actions, ctx)


class TrainedScorer:
    """Scores with a trained :class:`ScoringModel`, lazily loaded on first use.

    Mirrors ``SentenceTransformerEncoder``: the artifact is parsed on the first ``score``
    (or ``model_version`` read), so construction stays I/O-free and ``default_pipeline``
    remains pure.
    """

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._model: ScoringModel | None = None

    def _ensure_model(self) -> ScoringModel:
        if self._model is None:
            self._model = ScoringModel.load(self._model_path)
        return self._model

    @property
    def model_version(self) -> str:
        return self._ensure_model().model_version

    def score(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]:
        model = self._ensure_model()
        return [self._score_one(model, candidate, ctx) for candidate in candidates]

    def _score_one(
        self, model: ScoringModel, candidate: Candidate, ctx: RankingContext
    ) -> Candidate:
        _require_features(candidate)
        features = candidate.features
        assert features is not None

        probabilities = model.predict_proba(features_to_vector(features))
        actions = ActionScores(**probabilities)
        return _finalize(candidate, actions, ctx)


def default_scorer() -> Scorer:
    """Trained model if its artifact exists, else the heuristic (existence check only)."""
    if settings.scoring_model_path.exists():
        return TrainedScorer(settings.scoring_model_path)
    logger.warning(
        "scoring model artifact not found at %s — falling back to HeuristicScorer "
        "(run `make train` to train one)",
        settings.scoring_model_path,
    )
    return HeuristicScorer()
