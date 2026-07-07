"""Integration tests for context building (reference clock + personalization signals)."""

from __future__ import annotations

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.context import build_context, resolve_now
from foryou.candidates.hydrator import cosine_similarity
from tests.candidate_factories import (
    BASE_TIME,
    make_embedding,
    make_engagement,
    make_follow,
    make_post,
    make_user,
    unit_vector,
)


async def test_resolve_now_returns_the_latest_post_time(session: AsyncSession) -> None:
    author = await make_user(session, "author")
    await make_post(session, author, created_at=BASE_TIME - datetime.timedelta(days=3))
    latest = BASE_TIME - datetime.timedelta(hours=1)
    await make_post(session, author, created_at=latest)

    assert await resolve_now(session) == latest


async def test_resolve_now_falls_back_to_wall_clock_when_empty(session: AsyncSession) -> None:
    now = await resolve_now(session)

    assert now.tzinfo is not None  # timezone-aware wall-clock fallback


async def test_build_context_loads_followees_and_topics(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False, topics=["tech", "art"])
    followee = await make_user(session, "followee")
    await make_follow(session, reader, followee)

    ctx = await build_context(session, reader.id)

    assert ctx.followee_ids == frozenset({followee.id})
    assert set(ctx.user_topics) == {"tech", "art"}


async def test_interest_vector_is_the_mean_of_engaged_post_embeddings(
    session: AsyncSession,
) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    post = await make_post(session, author)
    await make_embedding(session, post, bump_index=5)
    await make_engagement(session, reader, post)

    ctx = await build_context(session, reader.id)

    assert ctx.user_interest_vector is not None
    assert cosine_similarity(ctx.user_interest_vector, tuple(unit_vector(5))) > 0.99


async def test_interest_vector_is_none_for_cold_start_user(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)

    ctx = await build_context(session, reader.id)

    assert ctx.user_interest_vector is None
