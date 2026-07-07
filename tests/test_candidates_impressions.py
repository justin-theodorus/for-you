"""Integration test for the impression-log side effect."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.impressions import ImpressionLogger
from foryou.candidates.types import ActionScores, Candidate, SourceName, SourceTag
from foryou.db.models import FeedImpression
from tests.candidate_factories import make_context, make_post, make_user


async def test_logs_one_row_per_candidate_with_audit_fields(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    post = await make_post(session, author)
    candidate = Candidate(
        post_id=post.id,
        sources=(SourceTag(SourceName.IN_NETWORK, 0.9), SourceTag(SourceName.TRENDING, 4.0)),
        author_id=author.id,
        action_scores=ActionScores(like=0.7, reply=0.1, repost=0.2, quote=0.05, dwell=0.6),
        score=1.65,
        rank=0,
    )
    ctx = make_context(reader.id)

    await ImpressionLogger().emit(session, [candidate], ctx)

    count = await session.scalar(select(func.count()).select_from(FeedImpression))
    assert count == 1
    row = await session.scalar(select(FeedImpression))
    assert row is not None
    assert row.request_id == ctx.request_id
    assert row.rank == 0
    assert row.final_score == 1.65
    assert {tag["source"] for tag in row.sources} == {"in_network", "trending"}
    assert row.action_scores["like"] == 0.7
    assert row.weight_vector == dict(ctx.weight_vector)


async def test_emit_is_a_noop_for_empty_selection(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)

    await ImpressionLogger().emit(session, [], make_context(reader.id))

    count = await session.scalar(select(func.count()).select_from(FeedImpression))
    assert count == 0


async def test_mmr_penalty_is_persisted_when_set(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    author = await make_user(session, "author")
    post = await make_post(session, author)
    candidate = Candidate(
        post_id=post.id,
        sources=(SourceTag(SourceName.OUT_OF_NETWORK, 0.5),),
        author_id=author.id,
        score=0.5,
        rank=0,
    )
    penalized = replace(candidate, mmr_penalty=0.25)

    await ImpressionLogger().emit(session, [penalized], make_context(reader.id))

    row = await session.scalar(select(FeedImpression))
    assert row is not None
    assert row.mmr_penalty == 0.25
