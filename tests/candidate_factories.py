"""Reusable arrange helpers + a context builder for candidate-pipeline tests.

Not collected by pytest (no ``test_`` prefix); imported like ``FakeEncoder`` is.
"""

from __future__ import annotations

import datetime
import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.types import (
    DEFAULT_WEIGHT_VECTOR,
    Candidate,
    RankingContext,
    SourceName,
    SourceTag,
)
from foryou.config import EMBEDDING_DIM
from foryou.db.enums import EngagementKind, PostKind, RelationshipKind
from foryou.db.models import Engagement, Follow, Post, PostEmbedding, User, UserRelationship

BASE_TIME = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)


def unit_vector(bump_index: int) -> list[float]:
    """Deterministic unit vector with one dimension emphasized (à la the smoke test)."""
    vec = [0.1] * EMBEDDING_DIM
    vec[bump_index % EMBEDDING_DIM] = 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


async def make_user(
    session: AsyncSession,
    handle: str,
    *,
    is_persona: bool = True,
    topics: list[str] | None = None,
) -> User:
    user = User(
        handle=handle,
        display_name=handle,
        is_persona=is_persona,
        persona_config={"topics": topics or []},
    )
    session.add(user)
    await session.flush()
    return user


async def make_post(
    session: AsyncSession,
    author: User,
    *,
    content: str = "post",
    topics: list[str] | None = None,
    created_at: datetime.datetime = BASE_TIME,
    like_count: int = 0,
) -> Post:
    post = Post(
        author_id=author.id,
        content=content,
        kind=PostKind.POST,
        topics=topics or [],
        created_at=created_at,
        like_count=like_count,
    )
    session.add(post)
    await session.flush()
    return post


async def make_follow(session: AsyncSession, follower: User, followee: User) -> None:
    session.add(Follow(follower_id=follower.id, followee_id=followee.id))
    await session.flush()


async def make_embedding(session: AsyncSession, post: Post, bump_index: int) -> None:
    session.add(
        PostEmbedding(post_id=post.id, embedding=unit_vector(bump_index), model_version="test")
    )
    await session.flush()


async def make_engagement(
    session: AsyncSession,
    user: User,
    post: Post,
    *,
    kind: EngagementKind = EngagementKind.LIKE,
    created_at: datetime.datetime = BASE_TIME,
) -> None:
    session.add(
        Engagement(user_id=user.id, post_id=post.id, kind=kind, created_at=created_at)
    )
    await session.flush()


async def make_block(session: AsyncSession, source: User, target: User) -> None:
    session.add(
        UserRelationship(
            source_user_id=source.id, target_user_id=target.id, kind=RelationshipKind.BLOCK
        )
    )
    await session.flush()


def make_context(
    user_id: uuid.UUID,
    *,
    now: datetime.datetime = BASE_TIME,
    followee_ids: frozenset[uuid.UUID] = frozenset(),
    topics: tuple[str, ...] = (),
    interest: tuple[float, ...] | None = None,
    limit: int = 50,
) -> RankingContext:
    """Construct a context directly for stage-level tests (no DB round-trip)."""
    return RankingContext(
        user_id=user_id,
        now=now,
        request_id="test-request",
        limit=limit,
        user_topics=topics,
        followee_ids=followee_ids,
        user_interest_vector=interest,
        weight_vector=dict(DEFAULT_WEIGHT_VECTOR),
    )


def bare_candidate(
    post_id: uuid.UUID | None = None, source: SourceName = SourceName.IN_NETWORK
) -> Candidate:
    """A minimal unhydrated candidate for pure-function tests."""
    return Candidate(post_id=post_id or uuid.uuid4(), sources=(SourceTag(source, 1.0),))
