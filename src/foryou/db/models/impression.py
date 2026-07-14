"""Feed-impression explainability log.

Written by ``ImpressionLogger`` (the pipeline's side-effect stage) at scoring time and read
back by ``GET /api/impressions/{request_id}``, so the "Why this post?" panel renders logged
data with no re-derivation — the plan.md audit requirement.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from foryou.db.base import Base
from foryou.db.mixins import created_at, uuid_pk


class FeedImpression(Base):
    """One logged feed candidate: its source(s), scores, active weights, and penalty."""

    __tablename__ = "feed_impressions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(Text, nullable=False)

    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    action_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    weight_vector: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # The active preference sliders (plan.md §4) and the resulting post-scoring multiplier,
    # so the audit panel can attribute the preference contribution with no re-derivation.
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    preference_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    mmr_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Which scorer produced final_score/action_scores, so the audit panel stays correct
    # across model retrains ("heuristic" for the fallback; the model_version otherwise).
    scoring_model_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = created_at()

    __table_args__ = (
        # Fetch a user's impressions for a request in rank order.
        Index("ix_feed_impressions_user_id_request_id", "user_id", "request_id"),
    )
