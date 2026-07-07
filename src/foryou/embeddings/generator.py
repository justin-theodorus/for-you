"""Backfill ``post_embeddings`` from post content.

Finds posts with no (or stale) embedding, encodes their content in batches, and
upserts one 384-dim vector per post. Commits per batch so a run is resumable and
memory-bounded: each committed batch stops matching the pending predicate, so the
same ``LIMIT`` query naturally advances with no cursor bookkeeping.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import settings
from foryou.db.models import Post, PostEmbedding
from foryou.embeddings.encoder import Encoder


def _pending_stmt(
    model_version: str, regenerate: bool, limit: int
) -> Select[tuple[uuid.UUID, str]]:
    """Select up to ``limit`` posts needing an embedding, ordered for determinism."""
    stmt = (
        select(Post.id, Post.content)
        .outerjoin(PostEmbedding, PostEmbedding.post_id == Post.id)
        .where(Post.content != "")  # skip empty content (also guards the loop)
        .order_by(Post.id)
        .limit(limit)
    )
    if regenerate:
        # Missing OR embedded by a different model version.
        return stmt.where(
            or_(
                PostEmbedding.post_id.is_(None),
                PostEmbedding.model_version != model_version,
            )
        )
    return stmt.where(PostEmbedding.post_id.is_(None))


async def generate_embeddings(
    session: AsyncSession,
    encoder: Encoder,
    *,
    batch_size: int = settings.embedding_batch_size,
    limit: int | None = None,
    regenerate: bool = False,
) -> int:
    """Encode and upsert embeddings for pending posts; return the number written.

    ``limit`` caps the total number of posts processed (useful for smoke runs);
    ``regenerate`` also re-embeds posts whose stored ``model_version`` differs from
    the encoder's.
    """
    written = 0
    while limit is None or written < limit:
        take = batch_size if limit is None else min(batch_size, limit - written)
        rows = (
            await session.execute(
                _pending_stmt(encoder.model_version, regenerate, take)
            )
        ).all()
        if not rows:
            break

        ids = [row[0] for row in rows]
        vectors = encoder.encode([row[1] for row in rows])
        payload = [
            {"post_id": pid, "embedding": vec, "model_version": encoder.model_version}
            for pid, vec in zip(ids, vectors, strict=True)
        ]

        stmt = pg_insert(PostEmbedding).values(payload)
        # post_id is the PK -> one embedding per post -> upsert, not insert.
        # created_at is left untouched: it is a creation timestamp, not a regen marker.
        stmt = stmt.on_conflict_do_update(
            index_elements=[PostEmbedding.post_id],
            set_={
                "embedding": stmt.excluded.embedding,
                "model_version": stmt.excluded.model_version,
            },
        )
        await session.execute(stmt)
        await session.commit()
        written += len(rows)

    return written
