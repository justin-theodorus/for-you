"""End-to-end data-layer smoke test.

Inserts a user, post, follow, engagement, and several post embeddings, then runs
a cosine-KNN query and prints the ranked similarities plus the query plan. Runs
inside a transaction that is rolled back, so it is idempotent and non-destructive.
"""

from __future__ import annotations

import asyncio
import math

from sqlalchemy import select, text

from foryou.config import EMBEDDING_DIM
from foryou.db.enums import EngagementKind, PostKind
from foryou.db.models import Engagement, Follow, Post, PostEmbedding, User
from foryou.db.session import SessionLocal

MODEL_VERSION = "smoke-test"


def seed_vector(bump_index: int) -> list[float]:
    """Deterministic unit vector with a single dimension emphasized."""
    vec = [0.1] * EMBEDDING_DIM
    vec[bump_index % EMBEDDING_DIM] = 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


async def main() -> None:
    async with SessionLocal() as session:
        # --- authors + a follow edge ---
        author = User(handle="smoke_author", display_name="Smoke Author", is_persona=True)
        reader = User(handle="smoke_reader", display_name="Smoke Reader")
        session.add_all([author, reader])
        await session.flush()

        session.add(Follow(follower_id=reader.id, followee_id=author.id))

        # --- a post + an engagement event ---
        post = Post(
            author_id=author.id,
            content="hello from the smoke test",
            kind=PostKind.POST,
            topics=["tech", "meta"],
        )
        session.add(post)
        await session.flush()
        session.add(
            Engagement(user_id=reader.id, post_id=post.id, kind=EngagementKind.LIKE)
        )

        # --- several post embeddings so cosine-KNN has something to rank ---
        session.add(
            PostEmbedding(
                post_id=post.id, embedding=seed_vector(0), model_version=MODEL_VERSION
            )
        )
        for i in range(1, 8):
            p = Post(author_id=author.id, content=f"filler {i}", kind=PostKind.POST)
            session.add(p)
            await session.flush()
            session.add(
                PostEmbedding(
                    post_id=p.id, embedding=seed_vector(i * 5), model_version=MODEL_VERSION
                )
            )
        await session.flush()

        # --- cosine-KNN: nearest embeddings to a query close to the first vector ---
        query = seed_vector(0)
        distance = PostEmbedding.embedding.cosine_distance(query)
        rows = (
            await session.execute(
                select(PostEmbedding.post_id, distance.label("distance"))
                .order_by(distance)
                .limit(5)
            )
        ).all()

        print("cosine-KNN results (nearest first):")
        for post_id, dist in rows:
            print(f"  post={post_id}  similarity={1 - dist:.4f}")
        assert rows[0].post_id == post.id, "expected the seeded post to be the nearest match"

        # --- confirm the KNN query can use the HNSW index ---
        plan = (
            await session.execute(
                text(
                    "EXPLAIN SELECT post_id FROM post_embeddings "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 5"
                ).bindparams(q=str(query))
            )
        ).all()
        print("\nquery plan:")
        for (line,) in plan:
            print(f"  {line}")

        # Roll back — nothing is persisted.
        await session.rollback()

    print("\nsmoke test passed ✅")


if __name__ == "__main__":
    asyncio.run(main())
