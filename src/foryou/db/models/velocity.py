"""Rolling engagement-velocity aggregates backing trends and niche/viral weighting."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from foryou.db.base import Base
from foryou.db.enums import VelocityWindow
from foryou.db.mixins import pg_enum, updated_at


class PostVelocity(Base):
    """Engagement count for a post over a fixed rolling window.

    Refreshed in batch by the world simulation (later slice); here it is schema
    plus indexing only.
    """

    __tablename__ = "post_velocity"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    window: Mapped[VelocityWindow] = mapped_column(
        pg_enum(VelocityWindow, "velocity_window"), primary_key=True
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = updated_at()
