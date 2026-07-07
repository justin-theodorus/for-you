"""Typed, swappable stage interfaces for the candidate pipeline.

Mirrors the ``Encoder`` protocol pattern in ``foryou.embeddings``: each stage is a
``runtime_checkable`` Protocol so real and fake implementations conform structurally
(no inheritance) and can be swapped or inspected independently. DB-touching stages
are ``async``; the pure ``features -> scores -> ranking`` stages are ``sync`` — that
split keeps ``Scorer`` the clean seam a trained model (plan.md §3) plugs into.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.types import Candidate, RankingContext, SourceName


@runtime_checkable
class Source(Protocol):
    """Generates raw, unhydrated candidates tagged with its own name."""

    name: SourceName

    async def fetch(self, session: AsyncSession, ctx: RankingContext) -> list[Candidate]: ...


@runtime_checkable
class Hydrator(Protocol):
    """The single I/O boundary: batch-loads posts + embeddings and assembles Features."""

    async def hydrate(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> list[Candidate]: ...


@runtime_checkable
class Filter(Protocol):
    """Drops candidates from the whole set (so block/mute can batch one query)."""

    async def apply(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> list[Candidate]: ...


@runtime_checkable
class Scorer(Protocol):
    """Pure features -> action scores + final score. Swap point for the trained model."""

    def score(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]: ...


@runtime_checkable
class Selector(Protocol):
    """Pure ranking over scored candidates. Swap point for MMR diversification."""

    def select(self, candidates: list[Candidate], ctx: RankingContext) -> list[Candidate]: ...


@runtime_checkable
class SideEffect(Protocol):
    """Persists the selected feed (e.g. the impression log). Library flushes."""

    async def emit(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> None: ...
