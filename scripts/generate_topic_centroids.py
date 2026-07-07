"""Backfill topic centroids into ``topic_centroids`` (plan.md §4 topic sliders).

Computes one mean embedding per topic from ``post_embeddings`` and upserts it. Commits
(like ``generate_embeddings.py``). Run after seeding and embedding:

    docker compose run --rm app python scripts/generate_topic_centroids.py
"""

from __future__ import annotations

import asyncio

from foryou.db.session import SessionLocal
from foryou.embeddings import generate_topic_centroids


async def main() -> None:
    async with SessionLocal() as session:
        written = await generate_topic_centroids(session)
    print(f"wrote {written} topic centroids")


if __name__ == "__main__":
    asyncio.run(main())
