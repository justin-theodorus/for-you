"""Posts and their thread / reply / quote relations."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from foryou.db.base import Base
from foryou.db.enums import PostKind
from foryou.db.mixins import created_at, pg_enum, uuid_pk


class Post(Base):
    """A single post. Replies and quotes are posts with the relevant link set."""

    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = uuid_pk()
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[PostKind] = mapped_column(
        pg_enum(PostKind, "post_kind"), nullable=False, default=PostKind.POST
    )

    # Conversation graph links (all self-referential, nulled if the target is removed).
    in_reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )
    quoted_post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )

    topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    # Denormalized display counters. Ground truth is the engagements event log.
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repost_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime.datetime] = created_at()

    __table_args__ = (
        # Flagship covering index for the in-network source ("recent posts by
        # followee"): WHERE author_id IN (...) ORDER BY created_at DESC. Postgres
        # scans this composite btree backward for DESC; INCLUDE(id) keeps the
        # candidate-id fetch index-only.
        Index(
            "ix_posts_author_id_created_at",
            "author_id",
            "created_at",
            postgresql_include=["id"],
        ),
        # Global recency / out-of-network fallback ordering.
        Index("ix_posts_created_at", "created_at"),
        # Thread / reply / quote traversal.
        Index("ix_posts_conversation_id", "conversation_id"),
        Index("ix_posts_in_reply_to_id", "in_reply_to_id"),
        Index("ix_posts_quoted_post_id", "quoted_post_id"),
        # Topic-slider filtering over the topic-tag array.
        Index("ix_posts_topics", "topics", postgresql_using="gin"),
    )
