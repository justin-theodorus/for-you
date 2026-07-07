"""Feature hydration — the pipeline's single I/O boundary.

Batch-loads each candidate's post row and (optional) embedding, then assembles the
plan.md §3 :class:`Features`. The pure feature math (``recency_decay``,
``cosine_similarity``) is exported so sources can reuse it for their provenance tags.
"""

from __future__ import annotations

import datetime
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.types import Candidate, Features, RankingContext
from foryou.config import settings
from foryou.db.models import Post, PostEmbedding

_LN2 = math.log(2.0)


def recency_decay(
    created_at: datetime.datetime, now: datetime.datetime, half_life_hours: float
) -> float:
    """Exponential decay in [0, 1]: 1.0 at ``now``, 0.5 one half-life earlier."""
    age_hours = max(0.0, (now - created_at).total_seconds() / 3600.0)
    return math.exp(-_LN2 * age_hours / half_life_hours)


def cosine_similarity(
    a: tuple[float, ...] | None, b: tuple[float, ...] | None
) -> float:
    """Cosine similarity of two vectors; 0.0 if either is missing or zero-norm."""
    if a is None or b is None:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class PostHydrator:
    """Loads post rows + embeddings in two batched queries and computes Features."""

    def __init__(self, *, half_life_hours: float = settings.recency_half_life_hours) -> None:
        self._half_life_hours = half_life_hours

    async def hydrate(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> list[Candidate]:
        if not candidates:
            return []

        post_ids = [candidate.post_id for candidate in candidates]
        posts = {
            post.id: post
            for post in await session.scalars(select(Post).where(Post.id.in_(post_ids)))
        }
        embeddings = {
            row.post_id: tuple(float(x) for x in row.embedding)
            for row in await session.scalars(
                select(PostEmbedding).where(PostEmbedding.post_id.in_(post_ids))
            )
        }

        hydrated: list[Candidate] = []
        for candidate in candidates:
            post = posts.get(candidate.post_id)
            if post is None:
                continue  # post deleted between generation and hydration
            embedding = embeddings.get(candidate.post_id)
            hydrated.append(
                Candidate(
                    post_id=candidate.post_id,
                    sources=candidate.sources,
                    author_id=post.author_id,
                    created_at=post.created_at,
                    topics=tuple(post.topics),
                    like_count=post.like_count,
                    reply_count=post.reply_count,
                    repost_count=post.repost_count,
                    quote_count=post.quote_count,
                    embedding=embedding,
                    features=self._features(post, embedding, ctx),
                )
            )
        return hydrated

    def _features(
        self, post: Post, embedding: tuple[float, ...] | None, ctx: RankingContext
    ) -> Features:
        counters = post.like_count + post.reply_count + post.repost_count + post.quote_count
        # The recency slider (plan.md §4) overrides the configured half-life per request.
        half_life_hours = ctx.half_life_hours or self._half_life_hours
        return Features(
            author_affinity=1.0 if post.author_id in ctx.followee_ids else 0.0,
            topic_match=_topic_match(tuple(post.topics), ctx.user_topics),
            recency=recency_decay(post.created_at, ctx.now, half_life_hours),
            engagement_velocity=math.log1p(counters),
            embedding_similarity=cosine_similarity(embedding, ctx.user_interest_vector),
        )


def _topic_match(post_topics: tuple[str, ...], user_topics: tuple[str, ...]) -> float:
    """Fraction of a post's topics the user is interested in."""
    if not post_topics:
        return 0.0
    overlap = len(set(post_topics) & set(user_topics))
    return overlap / len(post_topics)
