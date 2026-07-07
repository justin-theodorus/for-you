"""Integration tests for the three candidate sources."""

from __future__ import annotations

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.sources import InNetworkSource, OutOfNetworkSource, TrendingSource
from foryou.candidates.types import SourceName
from foryou.db.enums import EngagementKind
from tests.candidate_factories import (
    BASE_TIME,
    make_context,
    make_embedding,
    make_engagement,
    make_post,
    make_user,
    unit_vector,
)


async def test_in_network_returns_only_followee_posts_in_window(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    followee = await make_user(session, "followee")
    stranger = await make_user(session, "stranger")
    followee_post = await make_post(session, followee)
    await make_post(session, stranger)  # not followed -> excluded

    ctx = make_context(reader.id, followee_ids=frozenset({followee.id}))
    candidates = await InNetworkSource().fetch(session, ctx)

    assert [c.post_id for c in candidates] == [followee_post.id]
    assert candidates[0].sources[0].source is SourceName.IN_NETWORK


async def test_in_network_excludes_posts_older_than_lookback(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    followee = await make_user(session, "followee")
    recent = await make_post(session, followee, created_at=BASE_TIME)
    await make_post(session, followee, created_at=BASE_TIME - datetime.timedelta(days=30))

    ctx = make_context(reader.id, followee_ids=frozenset({followee.id}))
    candidates = await InNetworkSource(lookback_days=14).fetch(session, ctx)

    assert [c.post_id for c in candidates] == [recent.id]


async def test_in_network_empty_without_follows(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)

    candidates = await InNetworkSource().fetch(session, make_context(reader.id))

    assert candidates == []


async def test_out_of_network_ranks_by_similarity_excluding_followees(
    session: AsyncSession,
) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    followee = await make_user(session, "followee")
    near = await make_post(session, author, content="near")
    far = await make_post(session, author, content="far")
    followed_post = await make_post(session, followee, content="followed")
    await make_embedding(session, near, bump_index=0)
    await make_embedding(session, far, bump_index=100)
    await make_embedding(session, followed_post, bump_index=0)

    ctx = make_context(
        reader.id,
        followee_ids=frozenset({followee.id}),
        interest=tuple(unit_vector(0)),
    )
    candidates = await OutOfNetworkSource().fetch(session, ctx)

    post_ids = [c.post_id for c in candidates]
    assert followed_post.id not in post_ids  # followee excluded
    assert post_ids[0] == near.id  # most similar first


async def test_out_of_network_cold_start_falls_back_to_recency(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    older = await make_post(session, author, created_at=BASE_TIME - datetime.timedelta(hours=5))
    newer = await make_post(session, author, created_at=BASE_TIME)

    ctx = make_context(reader.id, interest=None)  # cold start
    candidates = await OutOfNetworkSource().fetch(session, ctx)

    assert [c.post_id for c in candidates] == [newer.id, older.id]
    assert all(c.sources[0].source is SourceName.OUT_OF_NETWORK for c in candidates)


async def test_trending_ranks_by_windowed_engagement_count(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    hot = await make_post(session, author, content="hot")
    warm = await make_post(session, author, content="warm")
    stale = await make_post(session, author, content="stale")
    flagged = await make_post(session, author, content="flagged")

    in_window = BASE_TIME - datetime.timedelta(hours=1)
    out_of_window = BASE_TIME - datetime.timedelta(hours=72)
    for handle in ("a", "b", "c"):
        engager = await make_user(session, f"engager_{handle}")
        await make_engagement(session, engager, hot, created_at=in_window)
    warm_engager = await make_user(session, "warm_engager")
    await make_engagement(session, warm_engager, warm, created_at=in_window)
    old_engager = await make_user(session, "old_engager")
    await make_engagement(session, old_engager, stale, created_at=out_of_window)
    reporter = await make_user(session, "reporter")
    await make_engagement(
        session, reporter, flagged, kind=EngagementKind.REPORT, created_at=BASE_TIME
    )

    ctx = make_context(reader.id)
    candidates = await TrendingSource(window_hours=48).fetch(session, ctx)

    post_ids = [c.post_id for c in candidates]
    assert post_ids == [hot.id, warm.id]  # stale (out of window) + flagged (report) excluded
    assert candidates[0].sources[0].score == 3.0
