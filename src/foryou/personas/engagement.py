"""Persona-facing engagement surface — reuses the seeder's heuristic (plan.md §6).

No LLM call per engagement: this is the cheap topic-overlap model shared with the
seeder via :func:`foryou.seed.build_engagements`, exposed here behind a typed
``EngagementActor`` so the generator doesn't thread raw tuples around.
"""

from __future__ import annotations

import datetime
import random
import uuid
from dataclasses import dataclass

from foryou.db.models import Engagement, Post
from foryou.seed import build_engagements


@dataclass(frozen=True)
class EngagementActor:
    """A user who may engage, plus the topics that bias what they engage with."""

    user_id: uuid.UUID
    topics: list[str]


def build_engagements_for_posts(
    rng: random.Random,
    actors: list[EngagementActor],
    posts: list[Post],
    per_user: int,
    *,
    base_time: datetime.datetime,
) -> list[Engagement]:
    """Heuristic engagements toward ``posts``; bumps post counters in place."""
    return build_engagements(
        rng,
        [(actor.user_id, actor.topics) for actor in actors],
        posts,
        per_user,
        base_time=base_time,
    )
