"""Candidate merging and filtering.

``merge_candidates`` is the pure, always-on dedupe step that collapses a post
surfaced by several sources into one candidate with merged provenance. The ``Filter``
classes are swappable stages that drop candidates (self-authored, blocked/muted).
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.types import Candidate, RankingContext
from foryou.db.models import UserRelationship


def merge_candidates(per_source: list[list[Candidate]]) -> list[Candidate]:
    """Dedupe by post id, concatenating each source's tag; keep first-seen order."""
    merged: dict[uuid.UUID, Candidate] = {}
    for candidates in per_source:
        for candidate in candidates:
            existing = merged.get(candidate.post_id)
            if existing is None:
                merged[candidate.post_id] = candidate
            else:
                merged[candidate.post_id] = replace(
                    existing, sources=existing.sources + candidate.sources
                )
    return list(merged.values())


class SelfFilter:
    """Drops the user's own posts."""

    async def apply(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> list[Candidate]:
        return [candidate for candidate in candidates if candidate.author_id != ctx.user_id]


class BlockMuteFilter:
    """Drops posts authored by users the requester has blocked or muted."""

    async def apply(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> list[Candidate]:
        if not candidates:
            return []
        blocked = frozenset(
            await session.scalars(
                select(UserRelationship.target_user_id).where(
                    UserRelationship.source_user_id == ctx.user_id
                )
            )
        )
        if not blocked:
            return candidates
        return [candidate for candidate in candidates if candidate.author_id not in blocked]
