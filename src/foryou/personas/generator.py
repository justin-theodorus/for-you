"""Orchestrate one bounded persona-generation run (plan.md §6).

Additive: personas + follows come from the seeder; this authors NEW LLM posts by the
existing personas and NEW heuristic engagements toward them. Structure (which persona
posts, ids, topics, timestamps, the engagement graph) is deterministic in ``seed``;
only the post *text* is LLM-nondeterministic — the same split the seeder uses.

The run is cost-visible and hard-capped: it stops once ``max_posts`` or ``max_tokens``
is reached, records spend in ``budget_ledger``, and returns a summary. Embeddings are
NOT generated here — run ``make embeddings`` (then ``make centroids``) afterward, the
idempotent backfill picks up the new posts.
"""

from __future__ import annotations

import datetime
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.budget import record_spend
from foryou.config import settings
from foryou.db.enums import PostKind
from foryou.db.models import Post, User
from foryou.personas.content import generate_post_text
from foryou.personas.engagement import EngagementActor, build_engagements_for_posts
from foryou.personas.llm import LLMClient
from foryou.personas.profiles import PersonaProfile, resolve_profile
from foryou.seed import BASE_TIME, POST_WINDOW_SECONDS, det_uuid


@dataclass
class PersonaGenConfig:
    """Knobs for a generation run. Caps default to the cost-bound settings."""

    posts_per_persona: int = 4
    engagements_per_user: int = 8
    seed: int = 42
    temperature: float = field(default_factory=lambda: settings.persona_temperature)
    max_tokens_per_post: int = field(default_factory=lambda: settings.persona_max_tokens)
    max_regenerations: int = field(
        default_factory=lambda: settings.persona_max_regenerations
    )
    max_posts: int = field(default_factory=lambda: settings.persona_posts_per_run)
    max_tokens: int = field(default_factory=lambda: settings.persona_tokens_per_run)


@dataclass
class GenerationSummary:
    """Cost-visible outcome of a run."""

    posts_inserted: int
    posts_rejected: int
    engagements: int
    tokens_used: int
    estimated_usd: float
    capped: bool


@dataclass(frozen=True)
class _PostSpec:
    """A planned post — everything decided in code, before any LLM call."""

    post_id: uuid.UUID
    author_id: uuid.UUID
    profile: PersonaProfile
    topic: str
    created_at: datetime.datetime


def _plan_posts(
    rng: random.Random, personas: Sequence[User], posts_per_persona: int
) -> list[_PostSpec]:
    """Deterministically decide ids/topics/timestamps — no text, no LLM.

    Consumes ``rng`` up front so the plan is reproducible independent of what the
    model later returns; text generation is a separate phase.
    """
    specs: list[_PostSpec] = []
    for user in personas:
        profile = resolve_profile(user)
        for _ in range(posts_per_persona):
            post_id = det_uuid(rng)
            topic = rng.choice(profile.topics)
            created_at = BASE_TIME - datetime.timedelta(
                seconds=rng.randint(0, POST_WINDOW_SECONDS)
            )
            specs.append(_PostSpec(post_id, user.id, profile, topic, created_at))
    return specs


async def generate_personas(
    session: AsyncSession,
    client: LLMClient,
    config: PersonaGenConfig | None = None,
) -> GenerationSummary:
    """Generate persona posts + heuristic engagements; return a cost-visible summary.

    Flushes but does not commit — the caller (the CLI) owns the commit, mirroring
    ``seed_world``.
    """
    config = config or PersonaGenConfig()
    # Namespaced string seed (Python hashes str via SHA-512, process-stable) so the
    # generator's det_uuid stream is reproducible yet can NEVER collide with the
    # seeder's Random(int) ids — a shared int seed would replay the seeder's uuids.
    rng = random.Random(f"foryou-personas:{config.seed}")

    personas = (
        await session.execute(
            select(User).where(User.is_persona.is_(True)).order_by(User.id)
        )
    ).scalars().all()

    specs = _plan_posts(rng, personas, config.posts_per_persona)

    posts: list[Post] = []
    seen: set[str] = set()
    tokens_used = 0
    rejected = 0
    capped = False
    for index, spec in enumerate(specs):
        if len(posts) >= config.max_posts:
            capped = True
            break
        if tokens_used + config.max_tokens_per_post > config.max_tokens:
            capped = True
            break
        text, spent = generate_post_text(
            client,
            spec.profile,
            spec.topic,
            seed=config.seed + index,
            max_tokens=config.max_tokens_per_post,
            temperature=config.temperature,
            max_regenerations=config.max_regenerations,
            seen=seen,
        )
        tokens_used += spent
        if text is None:
            rejected += 1
            continue
        posts.append(
            Post(
                id=spec.post_id,
                author_id=spec.author_id,
                content=text,
                kind=PostKind.POST,
                topics=[spec.topic],
                created_at=spec.created_at,
            )
        )

    session.add_all(posts)
    await session.flush()

    # Everyone (personas + readers) may engage with the new posts, biased by their
    # persona_config topics — reusing the seeder's heuristic so behavior can't drift.
    users = (await session.execute(select(User))).scalars().all()
    actors = [
        EngagementActor(user.id, list(user.persona_config.get("topics", [])))
        for user in users
    ]
    engagements = build_engagements_for_posts(
        rng, actors, posts, config.engagements_per_user, base_time=BASE_TIME
    )
    session.add_all(engagements)
    await session.flush()

    # Batch generation spends tokens but triggers no live reactions (plan.md §8 owns those).
    await record_spend(session, tokens=tokens_used, reactions=0)

    return GenerationSummary(
        posts_inserted=len(posts),
        posts_rejected=rejected,
        engagements=len(engagements),
        tokens_used=tokens_used,
        estimated_usd=tokens_used / 1_000_000 * settings.persona_usd_per_1m_tokens,
        capped=capped,
    )
