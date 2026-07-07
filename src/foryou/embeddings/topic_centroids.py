"""Backfill ``topic_centroids`` — one centroid embedding per topic (plan.md §4).

Each topic's centroid is the mean of the embeddings of every post tagged with it; the
topic sliders score a post by cosine similarity to a slider-weighted blend of these
centroids. Recomputed wholesale (idempotent upsert on the ``topic`` PK) rather than
incrementally, since the topic set is tiny and this runs offline after ``make embeddings``.

A post's ``topics`` array is unnested so multi-topic posts contribute to each of their
topics. Averaging happens in Python (mirrors ``_interest_vector``), reusing the proven
Vector-decode path instead of depending on a pgvector aggregate.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import EMBEDDING_DIM
from foryou.db.models import Post, PostEmbedding, TopicCentroid


async def generate_topic_centroids(session: AsyncSession) -> int:
    """Recompute every topic centroid from current post embeddings; return topics written."""
    topic_col = func.unnest(Post.topics).label("topic")
    rows = (
        await session.execute(
            select(topic_col, PostEmbedding.embedding).join(
                PostEmbedding, PostEmbedding.post_id == Post.id
            )
        )
    ).all()
    if not rows:
        return 0

    sums: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for topic, embedding in rows:
        running = sums.setdefault(topic, [0.0] * EMBEDDING_DIM)
        for index, value in enumerate(embedding):
            running[index] += float(value)
        counts[topic] = counts.get(topic, 0) + 1

    payload = [
        {"topic": topic, "embedding": [total / counts[topic] for total in running]}
        for topic, running in sums.items()
    ]

    stmt = pg_insert(TopicCentroid).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[TopicCentroid.topic],
        set_={"embedding": stmt.excluded.embedding, "updated_at": func.now()},
    )
    await session.execute(stmt)
    await session.commit()
    return len(payload)
