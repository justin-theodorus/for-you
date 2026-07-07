"""Integration tests for the deterministic world seeder."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.db.enums import EngagementKind
from foryou.db.models import Engagement, Follow, Post, User
from foryou.seed import SeedConfig, seed_world

# Small config with posts >> engagements_per_user so sampling never truncates,
# making row counts exact and easy to assert.
_CONFIG = SeedConfig(
    personas=4,
    readers=3,
    posts_per_persona=5,
    follows_per_user=3,
    engagements_per_user=4,
    seed=7,
)


async def _count(session: AsyncSession, model: type) -> int:
    total = await session.scalar(select(func.count()).select_from(model))
    return total or 0


async def test_seed_writes_expected_row_counts(session: AsyncSession) -> None:
    summary = await seed_world(session, _CONFIG)

    assert summary.users == 7  # 4 personas + 3 readers
    assert summary.posts == 20  # 4 personas * 5 posts
    assert summary.follows == 21  # 7 users * 3 follows
    assert summary.engagements == 28  # 7 users * 4 engagements
    assert await _count(session, User) == 7
    assert await _count(session, Post) == 20
    assert await _count(session, Follow) == 21
    assert await _count(session, Engagement) == 28


async def test_every_post_is_authored_by_a_persona(session: AsyncSession) -> None:
    await seed_world(session, _CONFIG)

    non_persona_posts = await session.scalar(
        select(func.count())
        .select_from(Post)
        .join(User, User.id == Post.author_id)
        .where(User.is_persona.is_(False))
    )
    assert non_persona_posts == 0


async def test_like_counters_match_the_engagement_log(session: AsyncSession) -> None:
    await seed_world(session, _CONFIG)

    counter_sum = await session.scalar(select(func.sum(Post.like_count)))
    like_events = await session.scalar(
        select(func.count())
        .select_from(Engagement)
        .where(Engagement.kind == EngagementKind.LIKE)
    )
    assert counter_sum == like_events


async def test_no_self_follows(session: AsyncSession) -> None:
    await seed_world(session, _CONFIG)

    self_follows = await session.scalar(
        select(func.count())
        .select_from(Follow)
        .where(Follow.follower_id == Follow.followee_id)
    )
    assert self_follows == 0


async def test_wipe_enables_deterministic_reseed(session: AsyncSession) -> None:
    first = await seed_world(session, _CONFIG)
    handles_first = set(
        (await session.execute(select(User.handle))).scalars().all()
    )

    second = await seed_world(session, SeedConfig(**{**_CONFIG.__dict__, "wipe": True}))
    handles_second = set(
        (await session.execute(select(User.handle))).scalars().all()
    )

    assert (first.users, first.posts, first.follows, first.engagements) == (
        second.users,
        second.posts,
        second.follows,
        second.engagements,
    )
    assert handles_first == handles_second  # same seed -> identical handles
    assert await _count(session, User) == 7  # wipe prevented duplication
