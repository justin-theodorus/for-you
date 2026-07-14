"""Immutable value types that flow through the candidate pipeline.

Every stage returns *new* objects (``dataclasses.replace``) rather than mutating in
place, so a candidate's provenance and scores are safe to share across stages and
snapshot into the impression log.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foryou.candidates.preferences import Preferences


class SourceName(enum.StrEnum):
    """Which candidate source surfaced a post."""

    IN_NETWORK = "in_network"
    OUT_OF_NETWORK = "out_of_network"
    TRENDING = "trending"


# Action vocabulary scored per candidate; also the keys of a weight vector.
ACTION_KEYS: tuple[str, ...] = ("like", "reply", "repost", "quote", "dwell")

# Uniform per-action weights: the score is a plain sum of the predicted probabilities.
# The preference layer (plan.md §4) deliberately does NOT tune this — it applies a
# transparent post-scoring `preference_multiplier` instead, which keeps the trained model
# (§3) valid with no retrain. A non-uniform vector stays available for offline weight
# experiments via `rank_feed(weight_vector=...)`; nothing in the UI sets one.
DEFAULT_WEIGHT_VECTOR: Mapping[str, float] = {key: 1.0 for key in ACTION_KEYS}


@dataclass(frozen=True, slots=True)
class SourceTag:
    """A single source's claim on a candidate, plus its source-local signal.

    ``score`` is the raw within-source ranking value (recency decay, cosine
    similarity, or velocity count) — provenance for the "Why this post?" panel, not
    the final score.
    """

    source: SourceName
    score: float


@dataclass(frozen=True, slots=True)
class Features:
    """The plan.md §3 feature set assembled by the hydrator, consumed by the scorer."""

    author_affinity: float
    topic_match: float
    recency: float
    engagement_velocity: float
    embedding_similarity: float


@dataclass(frozen=True, slots=True)
class ActionScores:
    """Predicted per-action probabilities produced by the scorer."""

    like: float
    reply: float
    repost: float
    quote: float
    dwell: float

    def as_dict(self) -> dict[str, float]:
        """JSON-friendly view for the impression log."""
        return {
            "like": self.like,
            "reply": self.reply,
            "repost": self.repost,
            "quote": self.quote,
            "dwell": self.dwell,
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    """A post moving through the pipeline, accreting provenance, features, and scores.

    Fields are filled progressively: sources at generation, the hydrated block after
    ``Hydrator``, and the scored block after ``Scorer``/``Selector``. ``mmr_penalty`` is set
    by ``MMRSelector`` (plan.md §5) and stays ``None`` for a candidate the selector dropped
    or for a pure-relevance ``TopKSelector`` run.
    """

    post_id: uuid.UUID
    sources: tuple[SourceTag, ...]

    # Hydrated from the posts / post_embeddings tables.
    author_id: uuid.UUID | None = None
    created_at: datetime.datetime | None = None
    topics: tuple[str, ...] = ()
    like_count: int = 0
    reply_count: int = 0
    repost_count: int = 0
    quote_count: int = 0
    embedding: tuple[float, ...] | None = None
    features: Features | None = None

    # Scored / selected.
    action_scores: ActionScores | None = None
    score: float | None = None
    # Post-scoring preference overlay applied to the model score (plan.md §4); 1.0 = no
    # effect. Persisted so the "Why this post?" panel shows the preference contribution.
    preference_multiplier: float | None = None
    mmr_penalty: float | None = None
    rank: int | None = None


@dataclass(frozen=True, slots=True)
class RankingContext:
    """Everything a pipeline run needs about the requesting user and the world clock.

    Loaded once by ``build_context`` and reused across stages. ``now`` is pinned to
    the corpus (``max(posts.created_at)``) rather than wall-clock so recency/trending
    windows land inside a frozen world and experiments stay reproducible.
    """

    user_id: uuid.UUID
    now: datetime.datetime
    request_id: str
    limit: int
    user_topics: tuple[str, ...]
    followee_ids: frozenset[uuid.UUID]
    user_interest_vector: tuple[float, ...] | None
    weight_vector: Mapping[str, float]
    # Stamped by the pipeline from the active scorer so the impression log records which
    # model produced the scores. None until the pipeline sets it (e.g. bare test contexts).
    scoring_model_version: str | None = None
    # Per-request MMR relevance weight (plan.md §5), set from the exploration slider
    # (plan.md §4) or an explicit rank_feed arg. None -> the selector's configured default.
    mmr_lambda: float | None = None

    # --- Preference layer (plan.md §4). Resolved from the request's Preferences by
    # build_context; every field defaults to a no-op so a neutral request and bare test
    # contexts reproduce the untuned feed. ---
    # Recency slider -> recency-decay half-life (hours). None -> the stage's own default.
    half_life_hours: float | None = None
    # Friends/global slider -> per-source score multiplier. None -> no source-mix boost.
    source_weights: Mapping[SourceName, float] | None = None
    # Niche/viral slider in [-1, 1]; 0.0 -> no engagement-velocity bias.
    velocity_bias: float = 0.0
    # Topic sliders -> slider-weighted blend of topic centroids. None -> no topic boost.
    topic_query_vector: tuple[float, ...] | None = None
    # The raw sliders, snapshotted for the impression audit log. None -> neutral.
    preferences: Preferences | None = None
