"""User-directed negative signals (block / mute) used as pipeline filters."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from foryou.db.base import Base
from foryou.db.enums import RelationshipKind
from foryou.db.mixins import created_at, pg_enum


class UserRelationship(Base):
    """``source_user_id`` blocks or mutes ``target_user_id``."""

    __tablename__ = "user_relationships"

    source_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[RelationshipKind] = mapped_column(
        pg_enum(RelationshipKind, "relationship_kind"), primary_key=True
    )
    created_at: Mapped[datetime.datetime] = created_at()
