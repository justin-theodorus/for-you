"""Tests for candidate merging (pure) and the filter stages (DB-backed)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.filters import BlockMuteFilter, SelfFilter, merge_candidates
from foryou.candidates.types import Candidate, SourceName, SourceTag
from tests.candidate_factories import make_block, make_context, make_user


def _candidate(post_id: uuid.UUID, author_id: uuid.UUID, source: SourceName) -> Candidate:
    return Candidate(post_id=post_id, sources=(SourceTag(source, 1.0),), author_id=author_id)


def test_merge_dedupes_by_post_id_and_concatenates_sources() -> None:
    post_id = uuid.uuid4()
    author_id = uuid.uuid4()
    in_network = [_candidate(post_id, author_id, SourceName.IN_NETWORK)]
    trending = [_candidate(post_id, author_id, SourceName.TRENDING)]

    merged = merge_candidates([in_network, trending])

    assert len(merged) == 1
    assert {tag.source for tag in merged[0].sources} == {
        SourceName.IN_NETWORK,
        SourceName.TRENDING,
    }


async def test_self_filter_drops_the_users_own_posts(session: AsyncSession) -> None:
    me = uuid.uuid4()
    other = uuid.uuid4()
    candidates = [
        _candidate(uuid.uuid4(), me, SourceName.IN_NETWORK),
        _candidate(uuid.uuid4(), other, SourceName.IN_NETWORK),
    ]

    kept = await SelfFilter().apply(session, candidates, make_context(me))

    assert [c.author_id for c in kept] == [other]


async def test_block_mute_filter_removes_blocked_authors(session: AsyncSession) -> None:
    reader = await make_user(session, "reader", is_persona=False)
    blocked = await make_user(session, "blocked")
    allowed = await make_user(session, "allowed")
    await make_block(session, reader, blocked)
    candidates = [
        _candidate(uuid.uuid4(), blocked.id, SourceName.OUT_OF_NETWORK),
        _candidate(uuid.uuid4(), allowed.id, SourceName.OUT_OF_NETWORK),
    ]

    kept = await BlockMuteFilter().apply(session, candidates, make_context(reader.id))

    assert [c.author_id for c in kept] == [allowed.id]
