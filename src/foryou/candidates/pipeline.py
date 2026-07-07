"""The composable candidate pipeline and its default wiring.

Runs the plan.md stages in order — Source -> merge/dedupe -> Hydrate -> Filter ->
Score -> Select -> SideEffect — over an immutable :class:`RankingContext`. Stages are
held as typed protocol instances, so any one is swappable in isolation.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.context import build_context
from foryou.candidates.filters import BlockMuteFilter, SelfFilter, merge_candidates
from foryou.candidates.hydrator import PostHydrator
from foryou.candidates.impressions import ImpressionLogger
from foryou.candidates.protocols import Filter, Hydrator, Scorer, Selector, SideEffect, Source
from foryou.candidates.scoring import default_scorer
from foryou.candidates.selection import TopKSelector
from foryou.candidates.sources import InNetworkSource, OutOfNetworkSource, TrendingSource
from foryou.candidates.types import Candidate, RankingContext
from foryou.config import settings


@dataclass(frozen=True, slots=True)
class CandidatePipeline:
    """An ordered composition of pipeline stages."""

    sources: tuple[Source, ...]
    hydrator: Hydrator
    filters: tuple[Filter, ...]
    scorer: Scorer
    selector: Selector
    side_effects: tuple[SideEffect, ...]

    async def run(self, session: AsyncSession, ctx: RankingContext) -> list[Candidate]:
        # Stamp the active scorer's version so the impression log is attributable across
        # retrains. getattr keeps arbitrary Scorer impls (e.g. test fakes) valid.
        ctx = replace(ctx, scoring_model_version=getattr(self.scorer, "model_version", None))
        # Sources share one session -> run sequentially (AsyncSession isn't concurrency-safe).
        gathered = [await source.fetch(session, ctx) for source in self.sources]
        candidates = merge_candidates(gathered)
        candidates = await self.hydrator.hydrate(session, candidates, ctx)
        for stage in self.filters:
            candidates = await stage.apply(session, candidates, ctx)
        candidates = self.scorer.score(candidates, ctx)
        candidates = self.selector.select(candidates, ctx)
        for effect in self.side_effects:
            await effect.emit(session, candidates, ctx)
        return candidates


def default_pipeline() -> CandidatePipeline:
    """The standard For You wiring (pure — constructs stages, touches no I/O)."""
    return CandidatePipeline(
        sources=(InNetworkSource(), OutOfNetworkSource(), TrendingSource()),
        hydrator=PostHydrator(),
        filters=(SelfFilter(), BlockMuteFilter()),
        scorer=default_scorer(),
        selector=TopKSelector(),
        side_effects=(ImpressionLogger(),),
    )


async def rank_feed(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime.datetime | None = None,
    request_id: str | None = None,
    limit: int = settings.feed_limit,
    weight_vector: dict[str, float] | None = None,
    pipeline: CandidatePipeline | None = None,
) -> list[Candidate]:
    """Build the context and run the pipeline — the single feed-ranking entrypoint."""
    ctx = await build_context(
        session,
        user_id,
        now=now,
        request_id=request_id,
        limit=limit,
        weight_vector=weight_vector,
    )
    return await (pipeline or default_pipeline()).run(session, ctx)
