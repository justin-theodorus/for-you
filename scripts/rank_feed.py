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

from foryou.candidates import Candidate, Preferences, rank_feed
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

    prefs = parser.add_argument_group("preference sliders (plan.md §4)", "each in [0,1]")
    prefs.add_argument("--recency", type=float, help="0=popularity/flat, 1=recency/steep.")
    prefs.add_argument(
        "--friends-global", type=float, help="0=friends only, 1=global only."
    )
    prefs.add_argument(
        "--niche-viral", type=float, help="0=niche/low-velocity, 1=viral/high-velocity."
    )
    prefs.add_argument(
        "--exploration", type=float, help="0=pure relevance, 1=max diversification (MMR)."
    )
    prefs.add_argument(
        "--topic",
        action="append",
        metavar="NAME=WEIGHT",
        help="Per-topic slider, repeatable (e.g. --topic tech=0.9 --topic politics=0.1).",
    )
    return parser


def _parse_topics(pairs: list[str] | None) -> dict[str, float]:
    weights: dict[str, float] = {}
    for pair in pairs or []:
        name, _, raw = pair.partition("=")
        if not name or not raw:
            raise SystemExit(f"--topic expects NAME=WEIGHT, got {pair!r}")
        weights[name] = float(raw)
    return weights


def _build_preferences(args: argparse.Namespace) -> Preferences | None:
    """A Preferences from any provided slider flags, or None when the request is neutral."""
    topics = _parse_topics(args.topic)
    provided = (
        args.recency,
        args.friends_global,
        args.niche_viral,
        args.exploration,
    )
    if all(value is None for value in provided) and not topics:
        return None
    return Preferences(
        recency=args.recency if args.recency is not None else 0.5,
        friends_global=args.friends_global if args.friends_global is not None else 0.5,
        niche_viral=args.niche_viral if args.niche_viral is not None else 0.5,
        topic_weights=topics,
        exploration=args.exploration,
    )


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


def _print_feed(
    user: User, candidates: list[Candidate], preferences: Preferences | None
) -> None:
    header = f"feed for @{user.handle} ({len(candidates)} items)"
    if preferences is not None:
        header += f"\npreferences: {preferences.as_dict()}"
    print(f"{header}\n")
    for candidate in candidates:
        sources = ",".join(tag.source.value for tag in candidate.sources)
        score = candidate.score if candidate.score is not None else float("nan")
        mult = candidate.preference_multiplier
        mult_str = f"  pref×{mult:.2f}" if mult is not None else ""
        print(
            f"  #{candidate.rank:<2} score={score:.3f}{mult_str}  [{sources}]  "
            f"post={candidate.post_id}"
        )
        if candidate.action_scores is not None:
            actions = " ".join(f"{k}={v:.2f}" for k, v in candidate.action_scores.as_dict().items())
            print(f"       {actions}")


async def main() -> None:
    args = build_parser().parse_args()
    now = datetime.datetime.fromisoformat(args.now) if args.now else None
    preferences = _build_preferences(args)
    async with SessionLocal() as session:
        user = await _resolve_user(session, args.handle, args.user_id)
        candidates = await rank_feed(
            session,
            user.id,
            now=now,
            request_id=args.request_id,
            limit=args.limit,
            preferences=preferences,
        )
        _print_feed(user, candidates, preferences)
        if args.persist:
            await session.commit()
            print(f"\npersisted {len(candidates)} impressions")
        else:
            await session.rollback()


if __name__ == "__main__":
    asyncio.run(main())
