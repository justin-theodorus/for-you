"""Integration tests exercising the schema against a live Postgres+pgvector DB."""

from __future__ import annotations

import math

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import EMBEDDING_DIM
from foryou.db.enums import EngagementKind, PostKind, RelationshipKind
from foryou.db.models import (
    Engagement,
    Follow,
    Post,
    PostEmbedding,
    User,
    UserRelationship,
)


def unit_vector(bump_index: int) -> list[float]:
    vec = [0.1] * EMBEDDING_DIM
    vec[bump_index % EMBEDDING_DIM] = 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


async def make_user(session: AsyncSession, handle: str, **kwargs: object) -> User:
    user = User(handle=handle, display_name=handle, **kwargs)
    session.add(user)
    await session.flush()
    return user


async def test_handle_is_unique(session: AsyncSession) -> None:
    await make_user(session, "dup")
    with pytest.raises(IntegrityError):
        # citext handle should collide case-insensitively.
        await make_user(session, "DUP")


async def test_handle_is_case_insensitive_lookup(session: AsyncSession) -> None:
    await make_user(session, "MixedCase")
    found = await session.scalar(select(User).where(User.handle == "mixedcase"))
    assert found is not None


async def test_follow_primary_key_dedupes(session: AsyncSession) -> None:
    a = await make_user(session, "a")
    b = await make_user(session, "b")
    session.add(Follow(follower_id=a.id, followee_id=b.id))
    await session.flush()
    session.add(Follow(follower_id=a.id, followee_id=b.id))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_engagement_event_insert(session: AsyncSession) -> None:
    author = await make_user(session, "author")
    reader = await make_user(session, "reader")
    post = Post(author_id=author.id, content="hi", kind=PostKind.POST)
    session.add(post)
    await session.flush()

    session.add(
        Engagement(
            user_id=reader.id,
            post_id=post.id,
            kind=EngagementKind.DWELL,
            value=1234.0,
        )
    )
    await session.flush()

    count = await session.scalar(
        select(func.count()).select_from(Engagement).where(Engagement.post_id == post.id)
    )
    assert count == 1


async def test_delete_post_cascades_to_children(session: AsyncSession) -> None:
    author = await make_user(session, "author")
    reader = await make_user(session, "reader")
    post = Post(author_id=author.id, content="hi", kind=PostKind.POST)
    session.add(post)
    await session.flush()
    session.add_all(
        [
            Engagement(user_id=reader.id, post_id=post.id, kind=EngagementKind.LIKE),
            PostEmbedding(post_id=post.id, embedding=unit_vector(3), model_version="t"),
        ]
    )
    await session.flush()

    await session.delete(post)
    await session.flush()

    engagements = await session.scalar(select(func.count()).select_from(Engagement))
    embeddings = await session.scalar(select(func.count()).select_from(PostEmbedding))
    assert engagements == 0
    assert embeddings == 0


async def test_block_relationship_row(session: AsyncSession) -> None:
    a = await make_user(session, "a")
    b = await make_user(session, "b")
    session.add(
        UserRelationship(
            source_user_id=a.id, target_user_id=b.id, kind=RelationshipKind.BLOCK
        )
    )
    await session.flush()

    blocked = await session.scalar(
        select(UserRelationship.target_user_id).where(
            UserRelationship.source_user_id == a.id,
            UserRelationship.kind == RelationshipKind.BLOCK,
        )
    )
    assert blocked == b.id


async def test_cosine_knn_ranks_nearest_first(session: AsyncSession) -> None:
    author = await make_user(session, "author")
    target_post: Post | None = None
    for i in range(6):
        post = Post(author_id=author.id, content=f"p{i}", kind=PostKind.POST)
        session.add(post)
        await session.flush()
        session.add(
            PostEmbedding(post_id=post.id, embedding=unit_vector(i * 7), model_version="t")
        )
        if i == 0:
            target_post = post
    await session.flush()
    assert target_post is not None

    query = unit_vector(0)
    distance = PostEmbedding.embedding.cosine_distance(query)
    nearest = await session.scalar(
        select(PostEmbedding.post_id).order_by(distance).limit(1)
    )
    assert nearest == target_post.id
