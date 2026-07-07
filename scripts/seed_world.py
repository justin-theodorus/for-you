"""Seed a reproducible synthetic world (users, posts, follows, engagements).

    docker compose run --rm app python scripts/seed_world.py --wipe

Re-seeding a populated DB needs --wipe (handles are unique). After seeding, run
`make embeddings` to populate post_embeddings over the new corpus.
"""

from __future__ import annotations

import argparse
import asyncio

from foryou.db.session import SessionLocal
from foryou.seed import SeedConfig, seed_world


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed a synthetic social world.")
    parser.add_argument("--personas", type=int, default=SeedConfig.personas)
    parser.add_argument("--readers", type=int, default=SeedConfig.readers)
    parser.add_argument("--posts-per-persona", type=int, default=SeedConfig.posts_per_persona)
    parser.add_argument("--follows-per-user", type=int, default=SeedConfig.follows_per_user)
    parser.add_argument("--engagements-per-user", type=int, default=SeedConfig.engagements_per_user)
    parser.add_argument("--seed", type=int, default=SeedConfig.seed)
    parser.add_argument(
        "--wipe", action="store_true", help="Delete the existing world before seeding."
    )
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    config = SeedConfig(
        personas=args.personas,
        readers=args.readers,
        posts_per_persona=args.posts_per_persona,
        follows_per_user=args.follows_per_user,
        engagements_per_user=args.engagements_per_user,
        seed=args.seed,
        wipe=args.wipe,
    )
    async with SessionLocal() as session:
        summary = await seed_world(session, config)
        await session.commit()
    print(
        f"seeded: {summary.users} users, {summary.posts} posts, "
        f"{summary.follows} follows, {summary.engagements} engagements"
    )


if __name__ == "__main__":
    asyncio.run(main())
