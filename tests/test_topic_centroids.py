"""Integration tests for the preference layer's DB-backed pieces (plan.md §4):

topic-centroid backfill, the build_context topic-query vector + half-life override, and
the impression audit of the sliders.
"""

from __future__ import annotations

import datetime
from dataclasses import replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.context import build_context
from foryou.candidates.hydrator import PostHydrator
from foryou.candidates.impressions import ImpressionLogger
from foryou.candidates.preferences import NEUTRAL, Preferences
from foryou.candidates.types import Candidate, SourceName, SourceTag
from foryou.db.models import FeedImpression, TopicCentroid
from foryou.embeddings import generate_topic_centroids
from tests.candidate_factories import (
    BASE_TIME,
    bare_candidate,
    make_context,
    make_embedding,
    make_post,
    make_user,
    unit_vector,
)

# --- topic-centroid backfill -------------------------------------------------------


async def test_backfill_computes_the_mean_embedding_per_topic(session: AsyncSession) -> None:
    author = await make_user(session, "author")
    tech_a = await make_post(session, author, topics=["tech"])
    tech_b = await make_post(session, author, topics=["tech"])
    art = await make_post(session, author, topics=["art"])
    await make_embedding(session, tech_a, bump_index=0)
    await make_embedding(session, tech_b, bump_index=1)
    await make_embedding(session, art, bump_index=2)

    written = await generate_topic_centroids(session)

    assert written == 2
    centroids = {row.topic: row.embedding for row in await session.scalars(select(TopicCentroid))}
    assert set(centroids) == {"tech", "art"}
    expected_tech = [(a + b) / 2.0 for a, b in zip(unit_vector(0), unit_vector(1), strict=True)]
    # pgvector stores float32, so compare with tolerance.
    for got, want in zip(centroids["tech"], expected_tech, strict=True):
        assert got == pytest.approx(want, abs=1e-6)
    for got, want in zip(centroids["art"], unit_vector(2), strict=True):
        assert got == pytest.approx(want, abs=1e-6)


async def test_backfill_is_idempotent(session: AsyncSession) -> None:
    author = await make_user(session, "author")
    post = await make_post(session, author, topics=["tech"])
    await make_embedding(session, post, bump_index=0)

    first = await generate_topic_centroids(session)
    second = await generate_topic_centroids(session)

    assert first == second == 1
    count = await session.scalar(select(func.count()).select_from(TopicCentroid))
    assert count == 1


# --- build_context: topic-query vector + half-life ---------------------------------


async def test_build_context_blends_centroids_for_non_neutral_topics(
    session: AsyncSession,
) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    post = await make_post(session, author, topics=["tech"])
    await make_embedding(session, post, bump_index=0)
    await generate_topic_centroids(session)

    ctx = await build_context(
        session, reader.id, preferences=Preferences(topic_weights={"tech": 1.0})
    )

    assert ctx.topic_query_vector is not None
    # weight 1.0 -> coeff +1.0 -> the tech centroid itself (unit_vector(0)), float32.
    for got, want in zip(ctx.topic_query_vector, unit_vector(0), strict=True):
        assert got == pytest.approx(want, abs=1e-6)


async def test_build_context_omits_topic_vector_when_all_topics_neutral(
    session: AsyncSession,
) -> None:
    reader = await make_user(session, "reader", is_persona=False)

    neutral = await build_context(session, reader.id, preferences=Preferences())
    half = await build_context(
        session, reader.id, preferences=Preferences(topic_weights={"tech": 0.5})
    )

    assert neutral.topic_query_vector is None
    assert half.topic_query_vector is None


async def test_build_context_resolves_recency_slider_into_half_life(
    session: AsyncSession,
) -> None:
    reader = await make_user(session, "reader", is_persona=False)

    ctx = await build_context(session, reader.id, preferences=Preferences(recency=1.0))

    assert ctx.half_life_hours is not None
    assert ctx.half_life_hours < 24.0  # steeper than the default


async def test_explicit_mmr_lambda_overrides_the_exploration_slider(
    session: AsyncSession,
) -> None:
    reader = await make_user(session, "reader", is_persona=False)

    ctx = await build_context(
        session, reader.id, mmr_lambda=0.9, preferences=Preferences(exploration=0.2)
    )

    assert ctx.mmr_lambda == 0.9


# --- hydrator honors the per-request half-life -------------------------------------


async def test_hydrator_uses_context_half_life_over_its_default(session: AsyncSession) -> None:
    author = await make_user(session, "author")
    day_old = await make_post(
        session, author, created_at=BASE_TIME - datetime.timedelta(hours=24)
    )
    candidate = bare_candidate(day_old.id)

    default_ctx = make_context(author.id, now=BASE_TIME)
    steep_ctx = make_context(author.id, now=BASE_TIME, half_life_hours=6.0)
    (default_hydrated,) = await PostHydrator().hydrate(session, [candidate], default_ctx)
    (steep_hydrated,) = await PostHydrator().hydrate(session, [candidate], steep_ctx)

    assert default_hydrated.features is not None and steep_hydrated.features is not None
    # A 24h-old post is exactly one default half-life old (recency 0.5); a 6h half-life
    # ages it four half-lives (recency 0.0625).
    assert default_hydrated.features.recency == 0.5
    assert steep_hydrated.features.recency < default_hydrated.features.recency


# --- impression audit of the sliders -----------------------------------------------


async def test_impression_logs_preferences_and_multiplier(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    post = await make_post(session, author)
    candidate = Candidate(
        post_id=post.id,
        sources=(SourceTag(SourceName.IN_NETWORK, 1.0),),
        author_id=author.id,
        score=1.3,
        preference_multiplier=1.3,
        rank=0,
    )
    ctx = replace(make_context(reader.id), preferences=Preferences(recency=0.9))

    await ImpressionLogger().emit(session, [candidate], ctx)

    row = await session.scalar(select(FeedImpression))
    assert row is not None
    assert row.preference_multiplier == 1.3
    assert row.preferences["recency"] == 0.9


async def test_impression_logs_neutral_when_no_preferences(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    post = await make_post(session, author)
    candidate = Candidate(
        post_id=post.id,
        sources=(SourceTag(SourceName.IN_NETWORK, 1.0),),
        author_id=author.id,
        score=1.0,
        rank=0,
    )

    await ImpressionLogger().emit(session, [candidate], make_context(reader.id))

    row = await session.scalar(select(FeedImpression))
    assert row is not None
    assert row.preferences == NEUTRAL.as_dict()
    assert row.preference_multiplier is None
