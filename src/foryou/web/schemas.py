"""Pydantic v2 request/response models — the JSON contract the demo frontend consumes.

Field shapes mirror the pipeline's own value types (``Candidate`` / ``Features`` /
``ActionScores``) and the ``feed_impressions`` audit row, so the "Why this post?" panel
renders logged data with no re-derivation.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from foryou.candidates import Preferences
from foryou.config import settings
from foryou.personas.profiles import MAX_POST_CHARS

# --- Preference / request inputs -------------------------------------------------------


class PreferencesIn(BaseModel):
    """The four §4 sliders plus per-topic weights, as sent by the control rail.

    Every slider is in ``[0, 1]`` with ``0.5`` neutral; a fully-neutral instance maps to
    ``None`` (:meth:`to_preferences`) so the untuned feed is reproduced exactly.
    """

    recency: float = Field(default=0.5, ge=0.0, le=1.0)
    friends_global: float = Field(default=0.5, ge=0.0, le=1.0)
    niche_viral: float = Field(default=0.5, ge=0.0, le=1.0)
    exploration: float | None = Field(default=None, ge=0.0, le=1.0)
    topic_weights: dict[str, float] = Field(default_factory=dict)

    @field_validator("topic_weights")
    @classmethod
    def _check_topic_weights(cls, value: dict[str, float]) -> dict[str, float]:
        for name, weight in value.items():
            if not 0.0 <= weight <= 1.0:
                raise ValueError(f"topic_weights[{name!r}] must be in [0, 1]")
        return value

    def is_neutral(self) -> bool:
        """True when every slider sits at its neutral centre (0.5 topics included)."""
        return (
            self.recency == 0.5
            and self.friends_global == 0.5
            and self.niche_viral == 0.5
            and self.exploration is None
            and all(weight == 0.5 for weight in self.topic_weights.values())
        )

    def to_preferences(self) -> Preferences | None:
        """Domain ``Preferences``, or ``None`` when neutral (reproduces the untuned feed)."""
        if self.is_neutral():
            return None
        return Preferences(
            recency=self.recency,
            friends_global=self.friends_global,
            niche_viral=self.niche_viral,
            topic_weights=dict(self.topic_weights),
            exploration=self.exploration,
        )


class FeedRequest(BaseModel):
    """Body for ``POST /api/feed``: who to rank for, how many, and the active sliders."""

    handle: str | None = None
    user_id: uuid.UUID | None = None
    limit: int = Field(default=settings.feed_limit, ge=1, le=200)
    preferences: PreferencesIn | None = None


# --- Shared views ----------------------------------------------------------------------


class AuthorView(BaseModel):
    id: uuid.UUID
    handle: str
    display_name: str
    is_persona: bool
    archetype: str | None = None
    bio: str | None = None


class SourceTagView(BaseModel):
    """One source's claim on a candidate, with its raw within-source signal."""

    source: str
    score: float


class ActionScoresView(BaseModel):
    like: float
    reply: float
    repost: float
    quote: float
    dwell: float


class FeaturesView(BaseModel):
    author_affinity: float
    topic_match: float
    recency: float
    engagement_velocity: float
    embedding_similarity: float


class WhyThisPost(BaseModel):
    """Per-post explainability payload — exactly what the impression log persists."""

    sources: list[SourceTagView]
    action_scores: ActionScoresView | None
    features: FeaturesView | None
    preference_multiplier: float | None
    mmr_penalty: float | None
    final_score: float | None
    rank: int | None


class FeedItem(BaseModel):
    post_id: uuid.UUID
    content: str
    created_at: datetime.datetime
    topics: list[str]
    like_count: int
    reply_count: int
    repost_count: int
    quote_count: int
    author: AuthorView
    rank: int | None
    final_score: float | None
    why: WhyThisPost


# --- Pipeline trace (the inspector panel) ----------------------------------------------


class StageCount(BaseModel):
    name: str
    count: int


class ScoreStats(BaseModel):
    min: float | None
    max: float | None
    mean: float | None


class PipelineTrace(BaseModel):
    """Live per-request candidate flow through the pipeline stages."""

    per_source: list[StageCount]
    candidates_total: int
    merged: int
    filters: list[StageCount]
    selected: int
    source_mix: list[StageCount]
    score_stats: ScoreStats
    diversified: int


class FeedResponse(BaseModel):
    request_id: str
    viewer: AuthorView
    limit: int
    model_version: str | None
    weight_vector: dict[str, float]
    preferences: dict[str, Any]
    trace: PipelineTrace
    items: list[FeedItem]


# --- Meta / read endpoints -------------------------------------------------------------


class UserSummary(BaseModel):
    id: uuid.UUID
    handle: str
    display_name: str
    is_persona: bool
    archetype: str | None = None


class PipelineStageDoc(BaseModel):
    key: str
    title: str
    description: str


class PostSummary(BaseModel):
    post_id: uuid.UUID
    content: str
    created_at: datetime.datetime
    topics: list[str]
    like_count: int
    reply_count: int
    repost_count: int
    quote_count: int


class ProfileView(BaseModel):
    user: AuthorView
    follower_count: int
    following_count: int
    post_count: int
    recent_posts: list[PostSummary]


class TrendItem(BaseModel):
    post_id: uuid.UUID
    content: str
    author: AuthorView
    velocity: float
    topics: list[str]
    like_count: int
    reply_count: int
    repost_count: int
    quote_count: int


class ImpressionView(BaseModel):
    """A persisted ``feed_impressions`` row — proves the audit trail round-trips the DB."""

    post_id: uuid.UUID
    rank: int | None
    final_score: float | None
    sources: list[Any]
    action_scores: dict[str, Any]
    weight_vector: dict[str, Any]
    preferences: dict[str, Any]
    preference_multiplier: float | None
    mmr_penalty: float | None
    scoring_model_version: str | None


# --- Live-trigger path (plan.md §8) ----------------------------------------------------


class PostCreate(BaseModel):
    """Body for ``POST /api/posts``: a real user's post, optionally triggering reactions.

    ``content`` is bounded here at the boundary *and* again in code when personas generate
    (``profiles.MAX_POST_CHARS``) — the same limit applies to humans and models.
    """

    handle: str | None = None
    user_id: uuid.UUID | None = None
    content: str = Field(min_length=1, max_length=MAX_POST_CHARS)
    in_reply_to_id: uuid.UUID | None = None
    topics: list[str] | None = None
    trigger_reactions: bool = True

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value.strip()


class ReactionView(BaseModel):
    """One persona reaction — a generated reply post."""

    persona_id: uuid.UUID
    persona_handle: str
    post_id: uuid.UUID
    content: str


class BudgetStatus(BaseModel):
    """Today's spend against today's caps (``budget_ledger``, keyed on the real UTC date)."""

    day: datetime.date
    tokens_used: int
    tokens_cap: int
    tokens_remaining: int
    reactions_used: int
    reactions_cap: int
    reactions_remaining: int
    exhausted: bool


class LivePostResponse(BaseModel):
    """What a live trigger did, and exactly what it cost."""

    post: PostSummary
    author: AuthorView
    reactions: list[ReactionView]
    rejected: list[str]  # safety-gate categories, one per dropped reply
    engagements: int
    tokens_used: int
    estimated_usd: float
    capped: bool
    cap_reason: str | None
    model_version: str
    budget: BudgetStatus
