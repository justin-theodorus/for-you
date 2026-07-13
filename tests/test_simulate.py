"""Integration tests for batch world generation (plan.md §7).

Runs inside the rolled-back fixture session: ``simulate_world`` flushes and the
fixture's savepoint contains it. The world is seeded inline first (simulate is additive
and requires existing personas).
"""

from __future__ import annotations

import datetime
import random
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.db.enums import Archetype, EngagementKind
from foryou.db.models import Engagement, Post, PostVelocity, User
from foryou.seed import BASE_TIME, SeedConfig, seed_world
from foryou.simulate import (
    VELOCITY_WINDOW_HOURS,
    SimulationConfig,
    _plan_tick_posts,
    refresh_post_velocity,
    simulate_world,
)

_SEED = SeedConfig(
    personas=4,
    readers=3,
    posts_per_persona=2,
    follows_per_user=2,
    engagements_per_user=3,
    seed=7,
)
_SIM = SimulationConfig(
    ticks=3, tick_hours=6.0, posts_per_persona=2, engagements_per_user=2, seed=7
)


async def _post_ids(session: AsyncSession) -> set[uuid.UUID]:
    return set((await session.execute(select(Post.id))).scalars().all())


async def test_writes_expected_post_count_and_advances_the_clock(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    before = await _post_ids(session)

    summary = await simulate_world(session, _SIM)

    # ticks * authoring personas * posts_per_persona; templated content has no dedupe.
    assert summary.posts == 3 * 4 * 2
    assert summary.ticks_run == 3
    new_ids = await _post_ids(session) - before
    assert len(new_ids) == summary.posts

    # Every simulated post lands strictly after BASE_TIME and within the run window.
    earliest_new = await session.scalar(
        select(func.min(Post.created_at)).where(Post.id.in_(new_ids))
    )
    latest_new = await session.scalar(
        select(func.max(Post.created_at)).where(Post.id.in_(new_ids))
    )
    assert earliest_new is not None and earliest_new > BASE_TIME
    assert latest_new is not None and latest_new <= summary.end_at

    # The ranking clock (max post time over the whole corpus) sits in the simulated future.
    latest = await session.scalar(select(func.max(Post.created_at)))
    assert latest is not None and latest > BASE_TIME
    assert summary.end_at == BASE_TIME + datetime.timedelta(hours=18)


async def test_is_additive_leaving_seed_content_intact(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    before = await _post_ids(session)

    summary = await simulate_world(session, _SIM)

    after = await _post_ids(session)
    assert before <= after  # seed posts untouched
    assert len(after - before) == summary.posts


async def test_engagement_counters_stay_consistent_with_the_log(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    before = await _post_ids(session)

    summary = await simulate_world(session, _SIM)

    assert summary.engagements > 0
    new_ids = await _post_ids(session) - before
    like_counter_sum = await session.scalar(
        select(func.coalesce(func.sum(Post.like_count), 0)).where(Post.id.in_(new_ids))
    )
    like_log = await session.scalar(
        select(func.count())
        .select_from(Engagement)
        .where(Engagement.post_id.in_(new_ids), Engagement.kind == EngagementKind.LIKE)
    )
    assert like_counter_sum == like_log


async def test_post_velocity_matches_the_engagement_aggregate(session: AsyncSession) -> None:
    await seed_world(session, _SEED)

    summary = await simulate_world(session, _SIM)

    assert summary.velocity_rows > 0
    for window, hours in VELOCITY_WINDOW_HOURS.items():
        window_start = summary.end_at - datetime.timedelta(hours=hours)
        expected = {
            post_id: count
            for post_id, count in (
                await session.execute(
                    select(Engagement.post_id, func.count())
                    .where(
                        Engagement.created_at > window_start,
                        Engagement.created_at <= summary.end_at,
                        Engagement.kind != EngagementKind.REPORT,
                    )
                    .group_by(Engagement.post_id)
                )
            ).all()
        }
        stored = {
            post_id: count
            for post_id, count in (
                await session.execute(
                    select(PostVelocity.post_id, PostVelocity.count).where(
                        PostVelocity.window == window
                    )
                )
            ).all()
        }
        assert stored == expected


async def test_velocity_refresh_is_wholesale_not_cumulative(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    summary = await simulate_world(session, _SIM)

    # Recomputing off the same clock replaces rows rather than appending duplicates.
    again = await refresh_post_velocity(session, now=summary.end_at)

    assert again == summary.velocity_rows
    total = await session.scalar(select(func.count()).select_from(PostVelocity))
    assert total == summary.velocity_rows


async def test_returns_empty_summary_when_world_is_unseeded(session: AsyncSession) -> None:
    summary = await simulate_world(session, _SIM)

    assert summary.ticks_run == 0
    assert summary.posts == 0
    assert summary.engagements == 0
    assert summary.velocity_rows == 0


def test_plan_tick_posts_is_deterministic_for_a_fixed_seed() -> None:
    personas = [
        User(id=uuid.uuid4(), handle=f"p{i}", display_name=f"P{i}", is_persona=True, archetype=arch)
        for i, arch in enumerate([Archetype.FOUNDER, Archetype.ENGINEER, Archetype.ARTIST])
    ]
    persona_topics = {
        personas[0].id: ["startups", "tech"],
        personas[1].id: ["tech", "programming"],
        personas[2].id: ["art", "culture"],
    }
    anchor = BASE_TIME + datetime.timedelta(hours=6)

    def plan() -> list[Post]:
        return _plan_tick_posts(
            random.Random("foryou-simulate:7"),
            personas,
            persona_topics,
            2,
            anchor=anchor,
            window_seconds=6 * 3600,
        )

    first, second = plan(), plan()

    assert [(p.id, p.author_id, p.content, p.created_at) for p in first] == [
        (p.id, p.author_id, p.content, p.created_at) for p in second
    ]
    assert len(first) == 6  # 3 personas * 2 posts
    assert all(BASE_TIME < p.created_at <= anchor for p in first)
