"""Batch world generation: advance the synthetic world by N ticks (plan.md §7).

Manually triggered, single-pass, bounded, cost-visible — no scheduler, no cron, no
background process. Additive over an already-seeded world (like ``foryou.personas``):
it reuses the existing persona users, authors NEW templated posts on a timeline that
advances *forward* from ``BASE_TIME``, engages them via the shared seeder heuristic,
then refreshes the ``post_velocity`` aggregate. It creates no users/follows and has no
``--wipe``.

Why forward-timeline works with zero pipeline changes: the ranking clock is pinned to
``max(posts.created_at)`` (``candidates.context.resolve_now``), so laying content after
``BASE_TIME`` moves ``ctx.now`` into the simulated future — recency/trending windows
follow, and the pre-``BASE_TIME`` seed corpus becomes the aged tail.

Determinism mirrors the seeder: everything (ids, timestamps, templated text) is a pure
function of ``config.seed`` and ``config.ticks`` — the same inputs reproduce a
byte-identical corpus. The run RNG is namespaced ``foryou-simulate:{seed}`` (Python
hashes str via SHA-512, process-stable) so its ``det_uuid`` stream can never collide
with the seeder's ``Random(int)`` ids or the persona path's ``foryou-personas:`` stream.
Consuming the RNG strictly in tick order makes ticks prefix-stable: ``--ticks 3`` and
``--ticks 5`` share ticks 0–2.

Content is templated (no LLM, no token spend, no ``budget_ledger`` writes). Embeddings
are NOT generated here — run ``make embeddings`` then ``make centroids`` afterward, the
idempotent backfills pick up the new posts.
"""

from __future__ import annotations

import datetime
import random
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.db.enums import EngagementKind, PostKind, VelocityWindow
from foryou.db.models import Engagement, Post, PostVelocity, User
from foryou.personas.engagement import EngagementActor, build_engagements_for_posts
from foryou.seed import BASE_TIME, TOPIC_CONTENT, det_uuid

# Rolling windows the batch refreshes, in hours off the final clock. Mirrors the
# VelocityWindow enum; the values match TrendingSource's on-the-fly aggregation.
VELOCITY_WINDOW_HOURS: dict[VelocityWindow, int] = {
    VelocityWindow.H1: 1,
    VelocityWindow.H6: 6,
    VelocityWindow.H24: 24,
}


@dataclass
class SimulationConfig:
    """Knobs for one bounded world-advance run. Defaults produce a small demo."""

    ticks: int = 6
    tick_hours: float = 12.0
    posts_per_persona: int = 2
    engagements_per_user: int = 6
    seed: int = 42


@dataclass
class TickSummary:
    """Per-tick row counts (part of the cost-visible summary)."""

    tick: int
    anchor: datetime.datetime
    posts: int
    engagements: int


@dataclass
class SimulationSummary:
    """Bounded, cost-visible outcome of a run (no tokens — content is templated)."""

    ticks_run: int
    posts: int
    engagements: int
    velocity_rows: int
    start_at: datetime.datetime
    end_at: datetime.datetime
    ticks: list[TickSummary] = field(default_factory=list)


async def refresh_post_velocity(
    session: AsyncSession, *, now: datetime.datetime
) -> int:
    """Recompute ``post_velocity`` wholesale off ``now``; return rows written.

    Idempotent snapshot (like ``generate_topic_centroids``): wipe then re-aggregate
    ``count(*)`` per post per window. Semantics mirror ``TrendingSource`` — a window is
    ``(now - hours, now]`` and ``report`` engagements are excluded — so a future
    table-backed trend would match the live aggregation exactly.
    """
    await session.execute(delete(PostVelocity))
    written = 0
    for window, hours in VELOCITY_WINDOW_HOURS.items():
        window_start = now - datetime.timedelta(hours=hours)
        rows = (
            await session.execute(
                select(Engagement.post_id, func.count().label("count"))
                .where(
                    Engagement.created_at > window_start,
                    Engagement.created_at <= now,
                    Engagement.kind != EngagementKind.REPORT,
                )
                .group_by(Engagement.post_id)
            )
        ).all()
        session.add_all(
            PostVelocity(post_id=post_id, window=window, count=count)
            for post_id, count in rows
        )
        written += len(rows)
    await session.flush()
    return written


def _plan_tick_posts(
    rng: random.Random,
    personas: list[User],
    persona_topics: dict[uuid.UUID, list[str]],
    posts_per_persona: int,
    *,
    anchor: datetime.datetime,
    window_seconds: int,
) -> list[Post]:
    """Templated posts for one tick, scattered in ``(anchor - window, anchor]``.

    Timestamps stay strictly after ``BASE_TIME`` (``window_seconds - 1`` upper bound),
    so simulated content always advances the clock past the seed corpus.
    """
    posts: list[Post] = []
    upper = max(0, window_seconds - 1)
    for persona in personas:
        topics = persona_topics[persona.id]
        for _ in range(posts_per_persona):
            topic = rng.choice(topics)
            created_at = anchor - datetime.timedelta(seconds=rng.randint(0, upper))
            posts.append(
                Post(
                    id=det_uuid(rng),
                    author_id=persona.id,
                    content=rng.choice(TOPIC_CONTENT[topic]),
                    kind=PostKind.POST,
                    topics=[topic],
                    created_at=created_at,
                )
            )
    return posts


async def simulate_world(
    session: AsyncSession, config: SimulationConfig | None = None
) -> SimulationSummary:
    """Advance the seeded world by ``config.ticks`` and return a cost-visible summary.

    Additive: requires an already-seeded world (persona users must exist); returns an
    empty summary if none do. Flushes per dependency level but does NOT commit — the
    caller (the CLI) owns the commit, mirroring ``seed_world`` / ``generate_personas``.
    """
    config = config or SimulationConfig()
    rng = random.Random(f"foryou-simulate:{config.seed}")

    personas = (
        await session.execute(
            select(User).where(User.is_persona.is_(True)).order_by(User.id)
        )
    ).scalars().all()
    persona_topics = {
        p.id: list(p.persona_config.get("topics", [])) for p in personas
    }
    # Only personas with a topic can author (guards against a persona seeded without
    # one; the topic must be a TOPIC_CONTENT key, which ARCHETYPE_TOPICS guarantees).
    authors = [p for p in personas if persona_topics[p.id]]

    start_at = BASE_TIME + datetime.timedelta(hours=config.tick_hours)
    end_at = BASE_TIME + datetime.timedelta(hours=config.ticks * config.tick_hours)
    if not authors:
        return SimulationSummary(
            ticks_run=0,
            posts=0,
            engagements=0,
            velocity_rows=0,
            start_at=start_at,
            end_at=BASE_TIME,
        )

    # Everyone (personas + readers) may engage the new posts, biased by their stored
    # persona_config topics — reusing the seeder heuristic so behavior can't drift.
    users = (await session.execute(select(User))).scalars().all()
    actors = [
        EngagementActor(user.id, list(user.persona_config.get("topics", [])))
        for user in users
    ]

    window_seconds = int(config.tick_hours * 3600)
    tick_summaries: list[TickSummary] = []
    total_posts = 0
    total_engagements = 0
    for k in range(config.ticks):
        anchor = BASE_TIME + datetime.timedelta(hours=(k + 1) * config.tick_hours)
        posts = _plan_tick_posts(
            rng,
            authors,
            persona_topics,
            config.posts_per_persona,
            anchor=anchor,
            window_seconds=window_seconds,
        )
        session.add_all(posts)
        await session.flush()

        engagements = build_engagements_for_posts(
            rng, actors, posts, config.engagements_per_user, base_time=anchor
        )
        session.add_all(engagements)
        await session.flush()

        total_posts += len(posts)
        total_engagements += len(engagements)
        tick_summaries.append(
            TickSummary(tick=k, anchor=anchor, posts=len(posts), engagements=len(engagements))
        )

    velocity_rows = await refresh_post_velocity(session, now=end_at)

    return SimulationSummary(
        ticks_run=config.ticks,
        posts=total_posts,
        engagements=total_engagements,
        velocity_rows=velocity_rows,
        start_at=start_at,
        end_at=end_at,
        ticks=tick_summaries,
    )
