"""Rank a For You feed for one user and print it with provenance and scores.

    docker compose run --rm app python scripts/rank_feed.py --handle reader_0 --limit 20

Rolls back by default (non-destructive, like verify_smoke). Pass --persist to commit
the feed_impressions rows written by the pipeline's impression logger. Requires a
seeded + embedded corpus (make seed && make embeddings).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates import Candidate, rank_feed
from foryou.config import settings
from foryou.db.models import User
from foryou.db.session import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank a For You feed for one user.")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--handle", help="User handle (default: first reader).")
    target.add_argument("--user-id", help="User UUID.")
    parser.add_argument("--limit", type=int, default=settings.feed_limit)
    parser.add_argument(
        "--now",
        help="ISO-8601 reference clock override (default: latest post time in the corpus).",
    )
    parser.add_argument("--request-id", help="Request id stamped on impressions.")
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Commit impression rows instead of rolling back.",
    )
    return parser


async def _resolve_user(
    session: AsyncSession, handle: str | None, user_id: str | None
) -> User:
    if user_id is not None:
        user = await session.get(User, uuid.UUID(user_id))
    elif handle is not None:
        user = await session.scalar(select(User).where(User.handle == handle))
    else:
        user = await session.scalar(
            select(User).where(User.is_persona.is_(False)).order_by(User.handle).limit(1)
        )
    if user is None:
        raise SystemExit("no matching user — seed the world first (make seed)")
    return user


def _print_feed(user: User, candidates: list[Candidate]) -> None:
    print(f"feed for @{user.handle} ({len(candidates)} items):\n")
    for candidate in candidates:
        sources = ",".join(tag.source.value for tag in candidate.sources)
        score = candidate.score if candidate.score is not None else float("nan")
        print(f"  #{candidate.rank:<2} score={score:.3f}  [{sources}]  post={candidate.post_id}")
        if candidate.action_scores is not None:
            actions = " ".join(f"{k}={v:.2f}" for k, v in candidate.action_scores.as_dict().items())
            print(f"       {actions}")


async def main() -> None:
    args = build_parser().parse_args()
    now = datetime.datetime.fromisoformat(args.now) if args.now else None
    async with SessionLocal() as session:
        user = await _resolve_user(session, args.handle, args.user_id)
        candidates = await rank_feed(
            session, user.id, now=now, request_id=args.request_id, limit=args.limit
        )
        _print_feed(user, candidates)
        if args.persist:
            await session.commit()
            print(f"\npersisted {len(candidates)} impressions")
        else:
            await session.rollback()


if __name__ == "__main__":
    asyncio.run(main())
