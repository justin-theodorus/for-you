"""Integration tests for the embedding backfill against a live Postgres+pgvector DB.

Uses the ``FakeEncoder`` (no torch/model). The generator commits per batch; the
``session`` fixture runs in create_savepoint mode so those commits stay contained
and are rolled back on teardown.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import EMBEDDING_DIM
from foryou.db.enums import PostKind
from foryou.db.models import Post, PostEmbedding, User
from foryou.embeddings.generator import generate_embeddings
from tests.test_encoder import FakeEncoder


async def _make_author(session: AsyncSession, handle: str = "author") -> User:
    user = User(handle=handle, display_name=handle)
    session.add(user)
    await session.flush()
    return user


async def _make_posts(session: AsyncSession, author: User, contents: list[str]) -> list[Post]:
    posts = [Post(author_id=author.id, content=c, kind=PostKind.POST) for c in contents]
    session.add_all(posts)
    await session.flush()
    return posts


async def _embedding_count(session: AsyncSession) -> int:
    count = await session.scalar(select(func.count()).select_from(PostEmbedding))
    return count or 0


async def test_backfills_one_embedding_per_post(session: AsyncSession) -> None:
    author = await _make_author(session)
    await _make_posts(session, author, ["alpha", "beta", "gamma"])

    written = await generate_embeddings(session, FakeEncoder(), batch_size=10)

    assert written == 3
    assert await _embedding_count(session) == 3


async def test_stores_correct_model_version_and_dimension(session: AsyncSession) -> None:
    author = await _make_author(session)
    (post,) = await _make_posts(session, author, ["only"])

    await generate_embeddings(session, FakeEncoder(model_version="fake-v1"), batch_size=10)

    row = await session.get(PostEmbedding, post.id)
    assert row is not None
    assert row.model_version == "fake-v1"
    assert len(row.embedding) == EMBEDDING_DIM


async def test_second_default_run_is_idempotent(session: AsyncSession) -> None:
    author = await _make_author(session)
    await _make_posts(session, author, ["a", "b"])
    await generate_embeddings(session, FakeEncoder(), batch_size=10)

    written = await generate_embeddings(session, FakeEncoder(), batch_size=10)

    assert written == 0
    assert await _embedding_count(session) == 2


async def test_regenerate_upserts_new_vector_and_version_but_keeps_created_at(
    session: AsyncSession,
) -> None:
    author = await _make_author(session)
    (post,) = await _make_posts(session, author, ["hello"])
    await generate_embeddings(session, FakeEncoder(model_version="fake-v1", salt=0), batch_size=10)
    original = await session.get(PostEmbedding, post.id)
    assert original is not None
    first_vector = list(original.embedding)
    first_created_at = original.created_at

    written = await generate_embeddings(
        session, FakeEncoder(model_version="fake-v2", salt=1), batch_size=10, regenerate=True
    )

    assert written == 1
    # The upsert runs at Core level, so reload the ORM object from the DB.
    await session.refresh(original)
    assert original.model_version == "fake-v2"
    assert list(original.embedding) != first_vector
    assert original.created_at == first_created_at  # creation timestamp preserved
    assert await _embedding_count(session) == 1  # upsert, not a second row


async def test_default_run_ignores_posts_with_current_version(session: AsyncSession) -> None:
    author = await _make_author(session)
    await _make_posts(session, author, ["x"])
    await generate_embeddings(session, FakeEncoder(model_version="fake-v1"), batch_size=10)

    # A different model version, but WITHOUT regenerate -> nothing re-embedded.
    written = await generate_embeddings(
        session, FakeEncoder(model_version="fake-v2"), batch_size=10
    )

    assert written == 0


async def test_limit_caps_total_posts_processed(session: AsyncSession) -> None:
    author = await _make_author(session)
    await _make_posts(session, author, [f"p{i}" for i in range(5)])

    written = await generate_embeddings(session, FakeEncoder(), batch_size=10, limit=2)

    assert written == 2
    assert await _embedding_count(session) == 2


async def test_processes_all_posts_across_multiple_batches(session: AsyncSession) -> None:
    author = await _make_author(session)
    await _make_posts(session, author, [f"p{i}" for i in range(5)])

    written = await generate_embeddings(session, FakeEncoder(), batch_size=2)

    assert written == 5
    assert await _embedding_count(session) == 5


async def test_skips_empty_content_posts(session: AsyncSession) -> None:
    author = await _make_author(session)
    await _make_posts(session, author, ["", "real", ""])

    written = await generate_embeddings(session, FakeEncoder(), batch_size=10)

    assert written == 1
    assert await _embedding_count(session) == 1
