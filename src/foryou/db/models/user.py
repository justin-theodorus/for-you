"""Users and personas."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import Boolean, Text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from foryou.db.base import Base
from foryou.db.enums import Archetype
from foryou.db.mixins import created_at, pg_enum, uuid_pk


class User(Base):
    """A network participant — either an LLM persona or a real user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    handle: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_persona: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archetype: Mapped[Archetype | None] = mapped_column(
        pg_enum(Archetype, "archetype"), nullable=True
    )
    # Structured persona config: interests, posting frequency/style, engagement
    # tolerance, follow-graph bias. Guardrails live in code, not this blob.
    persona_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    created_at: Mapped[datetime.datetime] = created_at()
