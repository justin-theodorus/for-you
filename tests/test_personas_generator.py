"""Integration tests for the persona generation orchestrator (plan.md §6).

Runs fully offline (FakeLLM, no OpenAI import) inside the rolled-back fixture session:
generate_personas flushes and the fixture's savepoint contains it.
"""

from __future__ import annotations

import datetime
import random
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.db.enums import Archetype, EngagementKind
from foryou.db.models import BudgetLedger, Engagement, Post, User
from foryou.personas import FakeLLM, PersonaGenConfig, generate_personas
from foryou.personas.generator import _plan_posts
from foryou.seed import SeedConfig, seed_world

_SEED = SeedConfig(
    personas=4,
    readers=3,
    posts_per_persona=2,
    follows_per_user=2,
    engagements_per_user=3,
    seed=7,
)


async def _post_ids(session: AsyncSession) -> set[uuid.UUID]:
    return set((await session.execute(select(Post.id))).scalars().all())


async def test_generates_posts_authored_only_by_personas(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    before = await _post_ids(session)

    summary = await generate_personas(
        session, FakeLLM(), PersonaGenConfig(seed=7, posts_per_persona=2, engagements_per_user=3)
    )

    # Every planned post is inserted or dropped by the dedupe gate (FakeLLM draws from
    # a finite pool, so occasional in-batch duplicates are expected and rejected).
    assert summary.posts_inserted + summary.posts_rejected == 8  # 4 personas * 2 posts
    assert summary.posts_inserted >= 1
    new_ids = await _post_ids(session) - before
    assert len(new_ids) == summary.posts_inserted

    non_persona = await session.scalar(
        select(func.count())
        .select_from(Post)
        .join(User, User.id == Post.author_id)
        .where(Post.id.in_(new_ids), User.is_persona.is_(False))
    )
    assert non_persona == 0


async def test_engagements_and_counters_are_consistent(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    before = await _post_ids(session)

    summary = await generate_personas(
        session, FakeLLM(), PersonaGenConfig(seed=7, posts_per_persona=2, engagements_per_user=3)
    )

    assert summary.engagements > 0
    new_ids = await _post_ids(session) - before

    # The like_count on the new posts must match the LIKE engagements toward them.
    like_counter_sum = await session.scalar(
        select(func.coalesce(func.sum(Post.like_count), 0)).where(Post.id.in_(new_ids))
    )
    like_log = await session.scalar(
        select(func.count())
        .select_from(Engagement)
        .where(Engagement.post_id.in_(new_ids), Engagement.kind == EngagementKind.LIKE)
    )
    assert like_counter_sum == like_log


async def test_budget_ledger_records_token_spend(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    today = datetime.datetime.now(datetime.UTC).date()
    before = await session.scalar(
        select(func.coalesce(BudgetLedger.tokens_used, 0)).where(BudgetLedger.day == today)
    ) or 0

    summary = await generate_personas(session, FakeLLM(), PersonaGenConfig(seed=7))

    after = await session.scalar(
        select(BudgetLedger.tokens_used).where(BudgetLedger.day == today)
    )
    assert summary.tokens_used > 0
    assert after == before + summary.tokens_used


async def test_max_posts_cap_short_circuits(session: AsyncSession) -> None:
    await seed_world(session, _SEED)

    summary = await generate_personas(
        session, FakeLLM(), PersonaGenConfig(seed=7, posts_per_persona=2, max_posts=3)
    )

    assert summary.capped is True
    assert summary.posts_inserted == 3


def test_plan_posts_is_deterministic_for_a_fixed_seed() -> None:
    personas = [
        User(handle=f"p{i}", display_name=f"P{i}", is_persona=True, archetype=arch)
        for i, arch in enumerate([Archetype.FOUNDER, Archetype.ENGINEER, Archetype.ARTIST])
    ]

    first = _plan_posts(random.Random(42), personas, 3)
    second = _plan_posts(random.Random(42), personas, 3)

    assert [(s.post_id, s.author_id, s.topic) for s in first] == [
        (s.post_id, s.author_id, s.topic) for s in second
    ]
    assert len(first) == 9  # 3 personas * 3 posts
