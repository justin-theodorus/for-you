"""Build the per-request :class:`RankingContext`.

Resolves the reference clock and loads the requesting user's personalization signals
once (follow set, topic interests, engagement-history interest vector) so the sources,
hydrator, and scorer all read from the same immutable context.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.types import DEFAULT_WEIGHT_VECTOR, RankingContext
from foryou.config import settings
from foryou.db.enums import EngagementKind
from foryou.db.models import Engagement, Follow, Post, PostEmbedding, User


async def resolve_now(session: AsyncSession) -> datetime.datetime:
    """Reference clock = the corpus's latest post time (falls back to wall-clock).

    Pinning to the corpus keeps recency/trending windows meaningful over a frozen,
    snapshot-able world instead of drifting past it as wall-clock advances.
    """
    latest = await session.scalar(select(Post.created_at).order_by(Post.created_at.desc()).limit(1))
    return latest or datetime.datetime.now(datetime.UTC)


async def _interest_vector(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[float, ...] | None:
    """Mean embedding of the posts this user positively engaged with, or ``None``.

    Stands in for the (currently unpopulated) ``user_embeddings`` table. Averaged in
    Python: the engaged-post set per user is tiny, and this reuses the proven Vector
    column decode path. A post engaged multiple times counts multiple times, which
    correctly biases the centroid toward stronger interests. ``report`` is excluded.
    """
    vectors = (
        await session.scalars(
            select(PostEmbedding.embedding)
            .join(Engagement, Engagement.post_id == PostEmbedding.post_id)
            .where(
                Engagement.user_id == user_id,
                Engagement.kind != EngagementKind.REPORT,
            )
        )
    ).all()
    if not vectors:
        return None

    dim = len(vectors[0])
    sums = [0.0] * dim
    for vector in vectors:
        for index, value in enumerate(vector):
            sums[index] += float(value)
    count = len(vectors)
    return tuple(total / count for total in sums)


async def build_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime.datetime | None = None,
    request_id: str | None = None,
    limit: int = settings.feed_limit,
    weight_vector: dict[str, float] | None = None,
) -> RankingContext:
    """Assemble the immutable context for one ranking request."""
    resolved_now = now or await resolve_now(session)
    followee_ids = frozenset(
        await session.scalars(
            select(Follow.followee_id).where(Follow.follower_id == user_id)
        )
    )
    user = await session.get(User, user_id)
    topics = tuple(user.persona_config.get("topics", [])) if user is not None else ()

    return RankingContext(
        user_id=user_id,
        now=resolved_now,
        request_id=request_id or str(uuid.uuid4()),
        limit=limit,
        user_topics=topics,
        followee_ids=followee_ids,
        user_interest_vector=await _interest_vector(session, user_id),
        weight_vector=weight_vector or dict(DEFAULT_WEIGHT_VECTOR),
    )
