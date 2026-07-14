"""Backfill ``post_embeddings`` from post content.

Finds posts with no (or stale) embedding, encodes their content in batches, and
upserts one 384-dim vector per post. Commits per batch so a run is resumable and
memory-bounded: each committed batch stops matching the pending predicate, so the
same ``LIMIT`` query naturally advances with no cursor bookkeeping.

The encode-and-upsert step itself is :func:`upsert_embeddings`, which only *flushes* —
the usual library-flushes/caller-commits split. The live-trigger path (plan.md §8) calls
it directly so a handful of new posts get embedded inside the caller's transaction; a
per-batch commit there would durably persist a half-written world if the subsequent LLM
call failed.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

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


async def upsert_embeddings(
    session: AsyncSession, encoder: Encoder, rows: Sequence[tuple[uuid.UUID, str]]
) -> int:
    """Encode ``(post_id, content)`` pairs and upsert their vectors; return rows written.

    Flushes but does **not** commit — the caller owns the transaction boundary.
    """
    if not rows:
        return 0
    # Encoding is a blocking torch forward pass. Off the event loop: this also runs on the
    # API request path (the live-trigger embeds inline) and must not stall the server.
    vectors = await asyncio.to_thread(encoder.encode, [content for _, content in rows])
    payload = [
        {"post_id": post_id, "embedding": vector, "model_version": encoder.model_version}
        for (post_id, _), vector in zip(rows, vectors, strict=True)
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
    await session.flush()
    return len(payload)


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

        written += await upsert_embeddings(
            session, encoder, [(row[0], row[1]) for row in rows]
        )
        # Commit per batch: the committed rows stop matching the pending predicate, so
        # the next LIMIT query advances on its own and a killed run resumes cleanly.
        await session.commit()

    return written
