"""Candidate sources: in-network recency, out-of-network similarity, trending velocity.

Each source returns thin (unhydrated) candidates carrying a single :class:`SourceTag`.
Sources run sequentially over the shared session (``AsyncSession`` is not
concurrency-safe); the tiny per-source work makes that a non-issue at this scale.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.hydrator import recency_decay
from foryou.candidates.types import Candidate, RankingContext, SourceName, SourceTag
from foryou.config import settings
from foryou.db.enums import EngagementKind
from foryou.db.models import Engagement, Post, PostEmbedding


class InNetworkSource:
    """Recent posts by followees — served by the ``posts(author_id, created_at)`` index."""

    name = SourceName.IN_NETWORK

    def __init__(
        self,
        *,
        lookback_days: int = settings.in_network_lookback_days,
        limit: int = settings.in_network_limit,
        half_life_hours: float = settings.recency_half_life_hours,
    ) -> None:
        self._lookback_days = lookback_days
        self._limit = limit
        self._half_life_hours = half_life_hours

    async def fetch(self, session: AsyncSession, ctx: RankingContext) -> list[Candidate]:
        if not ctx.followee_ids:
            return []
        # The recency slider (plan.md §4) overrides the configured half-life per request.
        half_life_hours = ctx.half_life_hours or self._half_life_hours
        window_start = ctx.now - datetime.timedelta(days=self._lookback_days)
        rows = (
            await session.execute(
                select(Post.id, Post.created_at)
                .where(
                    Post.author_id.in_(ctx.followee_ids),
                    Post.created_at <= ctx.now,
                    Post.created_at >= window_start,
                )
                .order_by(Post.created_at.desc())
                .limit(self._limit)
            )
        ).all()
        return [
            Candidate(
                post_id=post_id,
                sources=(
                    SourceTag(
                        SourceName.IN_NETWORK,
                        recency_decay(created_at, ctx.now, half_life_hours),
                    ),
                ),
            )
            for post_id, created_at in rows
        ]


class OutOfNetworkSource:
    """Posts similar to the user's interest vector via pgvector cosine KNN (HNSW index).

    Cold-start users (no embedded engagement history, so no interest vector) fall back
    to global recency, keeping exploration alive instead of returning nothing.
    """

    name = SourceName.OUT_OF_NETWORK

    def __init__(
        self,
        *,
        limit: int = settings.out_of_network_limit,
        half_life_hours: float = settings.recency_half_life_hours,
    ) -> None:
        self._limit = limit
        self._half_life_hours = half_life_hours

    async def fetch(self, session: AsyncSession, ctx: RankingContext) -> list[Candidate]:
        excluded = ctx.followee_ids | {ctx.user_id}
        if ctx.user_interest_vector is None:
            return await self._recency_fallback(session, ctx, excluded)

        distance = PostEmbedding.embedding.cosine_distance(list(ctx.user_interest_vector))
        rows = (
            await session.execute(
                select(Post.id, distance.label("distance"))
                .join(PostEmbedding, PostEmbedding.post_id == Post.id)
                .where(Post.author_id.notin_(excluded), Post.created_at <= ctx.now)
                .order_by(distance)
                .limit(self._limit)
            )
        ).all()
        return [
            Candidate(
                post_id=post_id,
                sources=(SourceTag(SourceName.OUT_OF_NETWORK, 1.0 - float(distance)),),
            )
            for post_id, distance in rows
        ]

    async def _recency_fallback(
        self, session: AsyncSession, ctx: RankingContext, excluded: frozenset[uuid.UUID]
    ) -> list[Candidate]:
        half_life_hours = ctx.half_life_hours or self._half_life_hours
        rows = (
            await session.execute(
                select(Post.id, Post.created_at)
                .where(Post.author_id.notin_(excluded), Post.created_at <= ctx.now)
                .order_by(Post.created_at.desc())
                .limit(self._limit)
            )
        ).all()
        return [
            Candidate(
                post_id=post_id,
                sources=(
                    SourceTag(
                        SourceName.OUT_OF_NETWORK,
                        recency_decay(created_at, ctx.now, half_life_hours),
                    ),
                ),
            )
            for post_id, created_at in rows
        ]


class TrendingSource:
    """Posts with the most engagement in a recent window off the reference clock.

    Aggregates the ``engagements`` log on the fly rather than reading ``post_velocity``, and
    that is a choice, not a stopgap: the batch simulation (plan.md §7) *does* populate that
    table, but it is a point-in-time snapshot, so a live-triggered reaction (plan.md §8)
    would not trend until the next ``make simulate``. Live aggregation also sidesteps the
    window mismatch — ``VelocityWindow`` offers h1/h6/h24, while the default trending window
    is 48h. ``report`` is excluded so flagged posts don't trend.
    """

    name = SourceName.TRENDING

    def __init__(
        self,
        *,
        window_hours: int = settings.trending_window_hours,
        limit: int = settings.trending_limit,
    ) -> None:
        self._window_hours = window_hours
        self._limit = limit

    async def fetch(self, session: AsyncSession, ctx: RankingContext) -> list[Candidate]:
        window_start = ctx.now - datetime.timedelta(hours=self._window_hours)
        velocity = func.count().label("velocity")
        rows = (
            await session.execute(
                select(Engagement.post_id, velocity)
                .where(
                    Engagement.created_at > window_start,
                    Engagement.created_at <= ctx.now,
                    Engagement.kind != EngagementKind.REPORT,
                )
                .group_by(Engagement.post_id)
                .order_by(velocity.desc())
                .limit(self._limit)
            )
        ).all()
        return [
            Candidate(
                post_id=post_id,
                sources=(SourceTag(SourceName.TRENDING, float(count)),),
            )
            for post_id, count in rows
        ]
