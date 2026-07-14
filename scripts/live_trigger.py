"""Publish a post as a real user and trigger bounded persona reactions (plan.md §8).

    docker compose run --rm app python scripts/live_trigger.py \
        --handle reader_0 --content "shipping the ranking inspector today"

Additive: run after `make seed` (+ `make embeddings` / `make centroids` so topics can be
inferred and the new content ranks). With OPENAI_API_KEY set it calls OpenAI; unset (or with
--fake) it uses the deterministic offline FakeLLM — no API calls, no cost. Like the seeder
this script commits.

Unlike `make personas` / `make simulate`, this embeds the new content inline, so the post and
its replies are immediately rankable — no follow-up `make embeddings` needed.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import settings
from foryou.db.models import Post, User
from foryou.db.session import SessionLocal
from foryou.embeddings import Encoder, SentenceTransformerEncoder
from foryou.live import LiveTriggerConfig, publish_and_react
from foryou.personas import FakeLLM, LLMClient, OpenAIClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish a post and trigger bounded persona reactions."
    )
    parser.add_argument("--handle", help="Author's handle; defaults to the first reader.")
    parser.add_argument("--content", required=True, help="The post text.")
    parser.add_argument("--in-reply-to", help="Post UUID this is a reply to.")
    parser.add_argument(
        "--topic",
        action="append",
        dest="topics",
        help="Tag the post with a topic (repeatable). Omit to infer from topic centroids.",
    )
    parser.add_argument(
        "--max-reactions",
        type=int,
        default=settings.live_max_reactions_per_action,
        help="Hard cap on persona reactions for this action.",
    )
    parser.add_argument(
        "--no-reactions",
        action="store_true",
        help="Publish only — trigger no persona reactions.",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Force the offline FakeLLM even if OPENAI_API_KEY is set.",
    )
    return parser


def _make_client(use_fake: bool) -> LLMClient:
    if use_fake or not settings.openai_api_key:
        if not use_fake:
            print("warning: OPENAI_API_KEY unset — using the offline FakeLLM.")
        return FakeLLM()
    return OpenAIClient(api_key=settings.openai_api_key)


async def _resolve_author(session: AsyncSession, handle: str | None) -> User:
    """The acting user: by handle, else the first real (non-persona) reader."""
    stmt = (
        select(User).where(User.handle == handle)
        if handle
        else select(User).where(User.is_persona.is_(False)).order_by(User.handle).limit(1)
    )
    user = await session.scalar(stmt)
    if user is None:
        raise SystemExit(f"no such user: {handle!r} — seed the world first (`make seed`).")
    return user


async def _resolve_parent(session: AsyncSession, post_id: str | None) -> Post | None:
    if post_id is None:
        return None
    parent = await session.get(Post, uuid.UUID(post_id))
    if parent is None:
        raise SystemExit(f"no such post: {post_id}")
    return parent


def _make_encoder() -> Encoder:
    return SentenceTransformerEncoder()


async def main() -> None:
    args = build_parser().parse_args()
    client = _make_client(args.fake)

    async with SessionLocal() as session:
        author = await _resolve_author(session, args.handle)
        parent = await _resolve_parent(session, args.in_reply_to)
        post, summary = await publish_and_react(
            session,
            author,
            args.content,
            client=client,
            encoder=_make_encoder(),
            topics=args.topics,
            in_reply_to=parent,
            react=not args.no_reactions,
            config=LiveTriggerConfig(max_reactions=args.max_reactions),
        )
        await session.commit()

    kind = "replied to" if parent is not None else "posted"
    print(
        f"{kind} {post.id} as @{author.handle} at {post.created_at:%Y-%m-%d %H:%M} "
        f"(world clock) topics={list(post.topics) or '—'}"
    )
    for reaction in summary.reactions:
        print(f"  @{reaction.persona_handle} replied: {reaction.content}")
    capped = f" [CAPPED: {summary.cap_reason}]" if summary.capped else ""
    rejected = f", {len(summary.rejected)} rejected" if summary.rejected else ""
    print(
        f"{len(summary.reactions)} reactions{rejected}, "
        f"{summary.engagements} engagements, "
        f"{summary.tokens_used} tokens (~${summary.estimated_usd:.4f})"
        f"{capped} [model={client.model_version}]"
    )
    budget = summary.budget
    print(
        f"budget {budget.day}: {budget.tokens_used}/{budget.tokens_cap} tokens · "
        f"{budget.reactions_used}/{budget.reactions_cap} reactions"
    )


if __name__ == "__main__":
    asyncio.run(main())
