"""Backfill post embeddings into ``post_embeddings``.

Unlike ``verify_smoke.py`` (which rolls back), this commits. Run inside Docker:

    docker compose run --rm app python scripts/generate_embeddings.py --limit 20

The first run downloads the sentence-transformers model (~90 MB) into HF_HOME,
which is cached on a named volume for subsequent runs.
"""

from __future__ import annotations

import argparse
import asyncio

from foryou.config import settings
from foryou.db.session import SessionLocal
from foryou.embeddings import SentenceTransformerEncoder, generate_embeddings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill post embeddings.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.embedding_batch_size,
        help="Posts encoded and upserted per batch.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the total number of posts processed (default: all pending).",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Also re-embed posts whose stored model_version differs from the current one.",
    )
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    encoder = SentenceTransformerEncoder(settings.embedding_model_name)
    async with SessionLocal() as session:
        written = await generate_embeddings(
            session,
            encoder,
            batch_size=args.batch_size,
            limit=args.limit,
            regenerate=args.regenerate,
        )
    print(f"wrote {written} embeddings (model_version={encoder.model_version})")


if __name__ == "__main__":
    asyncio.run(main())
