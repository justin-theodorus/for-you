"""Directed follow edges."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from foryou.db.base import Base
from foryou.db.mixins import created_at


class Follow(Base):
    """``follower_id`` follows ``followee_id``."""

    __tablename__ = "follows"

    follower_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    followee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime.datetime] = created_at()

    __table_args__ = (
        # "Who follows me" lookups. The composite PK already covers the
        # follower-side ("who I follow") used by the in-network source.
        Index("ix_follows_followee_id", "followee_id"),
    )
