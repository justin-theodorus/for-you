"""A non-invasive pipeline trace via counting proxies (plan.md §9 inspector).

Each proxy wraps a real pipeline stage, delegates to it, and records the size of what
flows through into a shared :class:`PipelineTraceData`. ``build_traced_pipeline`` swaps
the proxies into a copy of ``default_pipeline()`` — the pipeline core, the scorer, and
the impression logger are all left untouched, so the trace never changes ranking.

Stage counts the proxies can see:
- per-source raw candidates (each ``Source`` wrapper),
- the merged/deduped set (the ``Hydrator`` wrapper's *input* — the pipeline merges before
  hydration),
- survivors after each ``Filter``,
- the final selected feed (the ``Selector`` wrapper's output).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.pipeline import CandidatePipeline, default_pipeline
from foryou.candidates.protocols import Filter, Hydrator, Selector, Source
from foryou.candidates.types import Candidate, RankingContext, SourceName


@dataclass(slots=True)
class PipelineTraceData:
    """Mutable accumulator the proxies write to during one pipeline run."""

    per_source: dict[str, int] = field(default_factory=dict)
    merged: int = 0
    filters: list[tuple[str, int]] = field(default_factory=list)
    selected: int = 0
    # The per-action weight vector the run actually collapsed scores with. Captured from
    # ``ctx`` rather than assumed, so the API reports what the pipeline used and can't drift
    # from the persisted impression rows.
    weight_vector: Mapping[str, float] = field(default_factory=dict)


class _CountingSource:
    """``Source`` proxy that records how many raw candidates its inner source produced."""

    def __init__(self, inner: Source, trace: PipelineTraceData) -> None:
        self._inner = inner
        self._trace = trace
        self.name: SourceName = inner.name

    async def fetch(self, session: AsyncSession, ctx: RankingContext) -> list[Candidate]:
        out = await self._inner.fetch(session, ctx)
        self._trace.per_source[self.name.value] = len(out)
        return out


class _CountingHydrator:
    """``Hydrator`` proxy whose input length is the post-merge/dedupe candidate count."""

    def __init__(self, inner: Hydrator, trace: PipelineTraceData) -> None:
        self._inner = inner
        self._trace = trace

    async def hydrate(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> list[Candidate]:
        self._trace.merged = len(candidates)
        self._trace.weight_vector = ctx.weight_vector
        return await self._inner.hydrate(session, candidates, ctx)


class _CountingFilter:
    """``Filter`` proxy that records how many candidates survive it."""

    def __init__(self, inner: Filter, trace: PipelineTraceData) -> None:
        self._inner = inner
        self._trace = trace

    async def apply(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> list[Candidate]:
        out = await self._inner.apply(session, candidates, ctx)
        self._trace.filters.append((type(self._inner).__name__, len(out)))
        return out


class _CountingSelector:
    """``Selector`` proxy that records the final selected feed size."""

    def __init__(self, inner: Selector, trace: PipelineTraceData) -> None:
        self._inner = inner
        self._trace = trace

    def select(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]:
        out = self._inner.select(candidates, ctx)
        self._trace.selected = len(out)
        return out


def build_traced_pipeline(
    base: CandidatePipeline | None = None,
) -> tuple[CandidatePipeline, PipelineTraceData]:
    """Wrap a pipeline's stages in counting proxies; return it plus the live accumulator."""
    base = base or default_pipeline()
    trace = PipelineTraceData()
    traced = CandidatePipeline(
        sources=tuple(_CountingSource(source, trace) for source in base.sources),
        hydrator=_CountingHydrator(base.hydrator, trace),
        filters=tuple(_CountingFilter(stage, trace) for stage in base.filters),
        scorer=base.scorer,
        selector=_CountingSelector(base.selector, trace),
        side_effects=base.side_effects,
    )
    return traced, trace
