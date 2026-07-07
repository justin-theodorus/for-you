"""Append-only engagement event log — the scoring model's training data."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from foryou.db.base import Base
from foryou.db.enums import EngagementKind
from foryou.db.mixins import created_at, pg_enum, uuid_pk


class Engagement(Base):
    """A single post-directed interaction event."""

    __tablename__ = "engagements"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[EngagementKind] = mapped_column(
        pg_enum(EngagementKind, "engagement_kind"), nullable=False
    )
    # Optional magnitude, e.g. dwell milliseconds or scroll depth.
    value: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime.datetime] = created_at()

    __table_args__ = (
        # Per-post windowed aggregation for engagement velocity / trends.
        Index("ix_engagements_post_id_created_at", "post_id", "created_at"),
        # Per-user history used to build engagement-history embeddings.
        Index("ix_engagements_user_id_created_at", "user_id", "created_at"),
    )
