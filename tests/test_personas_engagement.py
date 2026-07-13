"""Unit tests for the heuristic engagement builder — no DB, no LLM.

Confirms the persona surface reuses the seeder heuristic faithfully: no self-
engagement, deterministic given a seed, and post counters consistent with the log.
"""

from __future__ import annotations

import datetime
import random
import uuid

from foryou.db.enums import EngagementKind
from foryou.db.models import Post
from foryou.personas.engagement import EngagementActor, build_engagements_for_posts
from foryou.seed import BASE_TIME, COUNTER_ATTR


def _make_posts(author_ids: list[uuid.UUID]) -> list[Post]:
    topics = [["tech"], ["food"], ["art"]]
    return [
        Post(
            id=uuid.uuid4(),
            author_id=author_ids[i % len(author_ids)],
            content=f"post {i}",
            topics=topics[i % len(topics)],
            created_at=BASE_TIME - datetime.timedelta(hours=i + 1),
        )
        for i in range(9)
    ]


def _actors(ids: list[uuid.UUID]) -> list[EngagementActor]:
    topic_sets = [["tech"], ["food"], ["art"]]
    return [EngagementActor(uid, topic_sets[i % len(topic_sets)]) for i, uid in enumerate(ids)]


def test_no_actor_engages_its_own_post() -> None:
    ids = [uuid.uuid4() for _ in range(3)]
    posts = _make_posts(ids)
    actors = _actors(ids)

    engagements = build_engagements_for_posts(
        random.Random(1), actors, posts, per_user=4, base_time=BASE_TIME
    )

    by_post = {p.id: p.author_id for p in posts}
    assert all(e.user_id != by_post[e.post_id] for e in engagements)


def test_counters_match_the_engagement_log() -> None:
    ids = [uuid.uuid4() for _ in range(3)]
    posts = _make_posts(ids)

    engagements = build_engagements_for_posts(
        random.Random(2), _actors(ids), posts, per_user=4, base_time=BASE_TIME
    )

    for kind, attr in COUNTER_ATTR.items():
        counter_sum = sum(getattr(p, attr) or 0 for p in posts)
        log_count = sum(1 for e in engagements if e.kind is kind)
        assert counter_sum == log_count


def test_is_deterministic_for_a_fixed_seed() -> None:
    ids = [uuid.uuid4() for _ in range(3)]
    posts_a = _make_posts(ids)
    posts_b = _make_posts(ids)
    # Same post ids so the two runs are comparable.
    for a, b in zip(posts_a, posts_b, strict=True):
        b.id = a.id

    first = build_engagements_for_posts(
        random.Random(5), _actors(ids), posts_a, per_user=3, base_time=BASE_TIME
    )
    second = build_engagements_for_posts(
        random.Random(5), _actors(ids), posts_b, per_user=3, base_time=BASE_TIME
    )

    assert [(e.user_id, e.post_id, e.kind) for e in first] == [
        (e.user_id, e.post_id, e.kind) for e in second
    ]


def test_no_engagement_dwell_value_is_negative() -> None:
    ids = [uuid.uuid4() for _ in range(3)]
    posts = _make_posts(ids)

    engagements = build_engagements_for_posts(
        random.Random(3), _actors(ids), posts, per_user=4, base_time=BASE_TIME
    )

    dwell_values = [e.value for e in engagements if e.kind is EngagementKind.DWELL]
    assert all(v is not None and v > 0 for v in dwell_values)
