"""Integration tests for the pipeline orchestrator: fakes for wiring, seeded world e2e."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.context import build_context
from foryou.candidates.pipeline import CandidatePipeline, default_pipeline, rank_feed
from foryou.candidates.scoring import HeuristicScorer
from foryou.candidates.selection import TopKSelector
from foryou.candidates.types import Candidate, Features, RankingContext, SourceName
from foryou.db.models import FeedImpression, User
from foryou.embeddings import generate_embeddings
from foryou.seed import SeedConfig, seed_world
from tests.candidate_factories import bare_candidate, make_context
from tests.test_encoder import FakeEncoder

# --- Fakes proving the stages are swappable via the protocols ---


class _FakeSource:
    def __init__(self, name: SourceName, candidates: list[Candidate]) -> None:
        self.name = name
        self._candidates = candidates

    async def fetch(self, session: AsyncSession, ctx: RankingContext) -> list[Candidate]:
        return list(self._candidates)


class _FakeHydrator:
    async def hydrate(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> list[Candidate]:
        features = Features(
            author_affinity=0.5,
            topic_match=0.5,
            recency=0.5,
            engagement_velocity=1.0,
            embedding_similarity=0.5,
        )
        return [replace(c, features=features) for c in candidates]


class _RecordingSideEffect:
    def __init__(self) -> None:
        self.received: list[Candidate] | None = None

    async def emit(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> None:
        self.received = list(candidates)


async def test_run_merges_sources_and_emits_the_selected_feed(session: AsyncSession) -> None:
    shared_id = bare_candidate().post_id
    in_net = _FakeSource(SourceName.IN_NETWORK, [bare_candidate(shared_id, SourceName.IN_NETWORK)])
    trending = _FakeSource(SourceName.TRENDING, [bare_candidate(shared_id, SourceName.TRENDING)])
    recorder = _RecordingSideEffect()
    pipeline = CandidatePipeline(
        sources=(in_net, trending),
        hydrator=_FakeHydrator(),
        filters=(),
        scorer=HeuristicScorer(),
        selector=TopKSelector(),
        side_effects=(recorder,),
    )
    ctx = make_context(bare_candidate().post_id, limit=5)

    result = await pipeline.run(session, ctx)

    assert len(result) == 1  # the two sources' shared post was deduped
    assert {tag.source for tag in result[0].sources} == {
        SourceName.IN_NETWORK,
        SourceName.TRENDING,
    }
    assert result[0].rank == 0
    assert recorder.received == result  # side effect saw the final selection


# --- End-to-end over a seeded, embedded world ---


async def _seed_and_embed(session: AsyncSession) -> None:
    config = SeedConfig(
        personas=6,
        readers=3,
        posts_per_persona=4,
        follows_per_user=3,
        engagements_per_user=5,
        seed=1,
    )
    await seed_world(session, config)
    await generate_embeddings(session, FakeEncoder(), batch_size=100)


async def test_default_pipeline_ranks_a_seeded_world(session: AsyncSession) -> None:
    await _seed_and_embed(session)
    reader = await session.scalar(
        select(User).where(User.is_persona.is_(False)).order_by(User.handle).limit(1)
    )
    assert reader is not None

    result = await rank_feed(session, reader.id, limit=10)

    assert result
    assert len(result) <= 10
    assert all(candidate.features is not None for candidate in result)
    assert all(candidate.sources for candidate in result)
    assert [candidate.rank for candidate in result] == list(range(len(result)))
    # The impression logger persisted exactly the selected feed.
    count = await session.scalar(select(func.count()).select_from(FeedImpression))
    assert count == len(result)


async def test_pipeline_is_deterministic_for_a_fixed_world(session: AsyncSession) -> None:
    await _seed_and_embed(session)
    reader = await session.scalar(
        select(User).where(User.is_persona.is_(False)).order_by(User.handle).limit(1)
    )
    assert reader is not None
    ctx = await build_context(session, reader.id, limit=10)
    pipeline = replace(default_pipeline(), side_effects=())  # skip impression writes

    first = await pipeline.run(session, ctx)
    second = await pipeline.run(session, ctx)

    assert [(c.post_id, c.score) for c in first] == [(c.post_id, c.score) for c in second]
