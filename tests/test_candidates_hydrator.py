"""Integration tests for feature hydration."""

from __future__ import annotations

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.hydrator import PostHydrator
from tests.candidate_factories import (
    BASE_TIME,
    bare_candidate,
    make_context,
    make_embedding,
    make_post,
    make_user,
    unit_vector,
)


async def test_hydrate_populates_post_fields_and_features(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False, topics=["tech"])
    author = await make_user(session, "author")
    post = await make_post(session, author, topics=["tech"], like_count=3)
    await make_embedding(session, post, bump_index=0)

    ctx = make_context(
        reader.id,
        followee_ids=frozenset({author.id}),
        topics=("tech",),
        interest=tuple(unit_vector(0)),
    )
    (hydrated,) = await PostHydrator().hydrate(session, [bare_candidate(post.id)], ctx)

    assert hydrated.author_id == author.id
    assert hydrated.topics == ("tech",)
    assert hydrated.like_count == 3
    assert hydrated.features is not None
    assert hydrated.features.author_affinity == 1.0  # author is a followee
    assert hydrated.features.topic_match == 1.0  # sole topic matches interest
    assert hydrated.features.embedding_similarity > 0.99


async def test_affinity_is_zero_for_non_followee(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    post = await make_post(session, author)

    ctx = make_context(reader.id, followee_ids=frozenset())
    (hydrated,) = await PostHydrator().hydrate(session, [bare_candidate(post.id)], ctx)

    assert hydrated.features is not None
    assert hydrated.features.author_affinity == 0.0


async def test_missing_embedding_yields_zero_similarity(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    post = await make_post(session, author)  # no embedding row

    ctx = make_context(reader.id, interest=tuple(unit_vector(0)))
    (hydrated,) = await PostHydrator().hydrate(session, [bare_candidate(post.id)], ctx)

    assert hydrated.embedding is None
    assert hydrated.features is not None
    assert hydrated.features.embedding_similarity == 0.0


async def test_recency_decays_with_age(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    fresh = await make_post(session, author, created_at=BASE_TIME)
    old = await make_post(session, author, created_at=BASE_TIME - datetime.timedelta(hours=48))

    ctx = make_context(reader.id, now=BASE_TIME)
    hydrated = await PostHydrator(half_life_hours=24.0).hydrate(
        session, [bare_candidate(fresh.id), bare_candidate(old.id)], ctx
    )

    by_id = {c.post_id: c for c in hydrated}
    fresh_features = by_id[fresh.id].features
    old_features = by_id[old.id].features
    assert fresh_features is not None and old_features is not None
    assert fresh_features.recency > old_features.recency
