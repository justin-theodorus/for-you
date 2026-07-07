"""Reusable column helpers shared across models."""

from __future__ import annotations

import datetime
import enum
import uuid

from sqlalchemy import DateTime, Enum, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


def pg_enum(py_enum: type[enum.Enum], name: str) -> Enum:
    """Native Postgres enum that stores the member *value* (lowercase strings)."""
    return Enum(
        py_enum,
        name=name,
        values_callable=lambda e: [member.value for member in e],
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    """Server-generated UUID primary key (gen_random_uuid, built in since pg13)."""
    return mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def created_at() -> Mapped[datetime.datetime]:
    """Timezone-aware creation timestamp defaulted server-side."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


def updated_at() -> Mapped[datetime.datetime]:
    """Timezone-aware last-updated timestamp defaulted (and bumped) server-side."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
