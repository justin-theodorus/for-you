"""Vector embeddings: per-post, per-user, and per-topic centroids.

Kept in dedicated tables (not columns on ``posts``/``users``) so the vector
index stays isolated and the hot recency-scan tables remain narrow.
"""

from __future__ import annotations

import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from foryou.config import EMBEDDING_DIM
from foryou.db.base import Base
from foryou.db.mixins import created_at, updated_at


class PostEmbedding(Base):
    """Content embedding for a post — backs the out-of-network similarity source."""

    __tablename__ = "post_embeddings"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = created_at()

    __table_args__ = (
        # Approximate-nearest-neighbour index for cosine similarity (the `<=>`
        # operator). HNSW over IVFFlat: better recall/latency and no training
        # step; the higher build cost is negligible at this scale.
        Index(
            "ix_post_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class UserEmbedding(Base):
    """Engagement-history / interest centroid — backs personalization."""

    __tablename__ = "user_embeddings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    updated_at: Mapped[datetime.datetime] = updated_at()


class TopicCentroid(Base):
    """Centroid embedding per topic — backs the topic sliders (cosine to centroid)."""

    __tablename__ = "topic_centroids"

    topic: Mapped[str] = mapped_column(Text, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    updated_at: Mapped[datetime.datetime] = updated_at()
