"""Bring a fresh deployment's world up in one idempotent command.

    docker compose run --rm app python scripts/bootstrap.py     # make bootstrap
    fly ssh console -C "python scripts/bootstrap.py"            # make fly-bootstrap

Seeds, embeds, and computes topic centroids, skipping entirely if a world already exists —
so it is safe to re-run and cheap when there is nothing to do. It never trains: the scorer
artifact ships in the image (see foryou.bootstrap). Run migrations first; on Fly the release
command does that on every deploy.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from foryou.bootstrap import ScoringArtifactMissing, bootstrap
from foryou.config import settings
from foryou.db.session import SessionLocal
from foryou.embeddings import SentenceTransformerEncoder
from foryou.seed import SeedConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap the demo world (idempotent).")
    parser.add_argument("--seed", type=int, default=SeedConfig.seed)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-seed even if a world already exists (wipes it first).",
    )
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    encoder = SentenceTransformerEncoder(settings.embedding_model_name)
    try:
        async with SessionLocal() as session:
            summary = await bootstrap(
                session,
                encoder,
                config=SeedConfig(seed=args.seed),
                force=args.force,
            )
            await session.commit()
    except ScoringArtifactMissing as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    if summary.skipped:
        print("world already bootstrapped — nothing to do")
        return
    print(
        f"bootstrapped: {summary.users} users, {summary.posts} posts, "
        f"{summary.embeddings} embeddings, {summary.centroids} topic centroids"
    )


if __name__ == "__main__":
    asyncio.run(main())
