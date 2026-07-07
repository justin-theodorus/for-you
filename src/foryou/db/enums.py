"""Enumerations backing native Postgres enum columns."""

from __future__ import annotations

import enum


class Archetype(enum.StrEnum):
    """Persona archetype used to shape generated behavior and content."""

    FOUNDER = "founder"
    JOURNALIST = "journalist"
    MEME = "meme"
    TRADER = "trader"
    POLITICIAN = "politician"
    ENGINEER = "engineer"
    ARTIST = "artist"
    OTHER = "other"


class PostKind(enum.StrEnum):
    """Structural type of a post within the conversation graph."""

    POST = "post"
    REPLY = "reply"
    QUOTE = "quote"


class EngagementKind(enum.StrEnum):
    """Post-directed interaction recorded in the engagement event log."""

    LIKE = "like"
    REPLY = "reply"
    REPOST = "repost"
    QUOTE = "quote"
    CLICK = "click"
    DWELL = "dwell"
    REPORT = "report"


class RelationshipKind(enum.StrEnum):
    """User-directed negative signal used as a pipeline filter."""

    BLOCK = "block"
    MUTE = "mute"


class VelocityWindow(enum.StrEnum):
    """Rolling time window for engagement-velocity aggregates."""

    H1 = "h1"
    H6 = "h6"
    H24 = "h24"
