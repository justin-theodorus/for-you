"""Build the per-request :class:`RankingContext`.

Resolves the reference clock and loads the requesting user's personalization signals
once (follow set, topic interests, engagement-history interest vector) so the sources,
hydrator, and scorer all read from the same immutable context.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.preferences import NEUTRAL, Preferences, resolve_preferences
from foryou.candidates.types import DEFAULT_WEIGHT_VECTOR, RankingContext
from foryou.config import settings
from foryou.db.enums import EngagementKind
from foryou.db.models import Engagement, Follow, Post, PostEmbedding, TopicCentroid, User


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


async def _topic_query_vector(
    session: AsyncSession, topic_weights: Mapping[str, float]
) -> tuple[float, ...] | None:
    """Slider-weighted blend of topic centroids (plan.md §4), or ``None`` if it vanishes.

    Each topic contributes ``(weight - 0.5) * 2`` (a signed pull in ``[-1, 1]``) times its
    centroid, so neutral (0.5) topics drop out and a topic can be actively suppressed.
    Returns ``None`` when no topic is non-neutral, no centroid exists, or the blend is
    zero — all of which the scorer treats as "no topic boost".
    """
    coeffs = {t: (w - 0.5) * 2.0 for t, w in topic_weights.items() if w != 0.5}
    if not coeffs:
        return None
    centroids = {
        row.topic: row.embedding
        for row in await session.scalars(
            select(TopicCentroid).where(TopicCentroid.topic.in_(coeffs))
        )
    }
    if not centroids:
        return None

    dim = len(next(iter(centroids.values())))
    blend = [0.0] * dim
    for topic, coeff in coeffs.items():
        centroid = centroids.get(topic)
        if centroid is None:
            continue
        for index, value in enumerate(centroid):
            blend[index] += coeff * float(value)
    if not any(blend):
        return None
    return tuple(blend)


async def build_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime.datetime | None = None,
    request_id: str | None = None,
    limit: int = settings.feed_limit,
    weight_vector: dict[str, float] | None = None,
    mmr_lambda: float | None = None,
    preferences: Preferences | None = None,
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

    resolved = resolve_preferences(preferences or NEUTRAL)
    topic_query_vector = (
        await _topic_query_vector(session, preferences.topic_weights)
        if preferences is not None
        else None
    )

    return RankingContext(
        user_id=user_id,
        now=resolved_now,
        request_id=request_id or str(uuid.uuid4()),
        limit=limit,
        user_topics=topics,
        followee_ids=followee_ids,
        user_interest_vector=await _interest_vector(session, user_id),
        weight_vector=weight_vector or dict(DEFAULT_WEIGHT_VECTOR),
        # An explicit mmr_lambda arg still wins over the exploration slider.
        mmr_lambda=mmr_lambda if mmr_lambda is not None else resolved.mmr_lambda,
        half_life_hours=resolved.half_life_hours,
        source_weights=resolved.source_weights,
        velocity_bias=resolved.velocity_bias,
        topic_query_vector=topic_query_vector,
        preferences=preferences,
    )
