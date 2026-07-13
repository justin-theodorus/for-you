"""Generate LLM persona posts + heuristic engagements over the seeded world (plan.md §6).

    docker compose run --rm app python scripts/generate_personas.py --posts-per-persona 3

Additive: run after `make seed`. With OPENAI_API_KEY set it calls OpenAI; unset (or
with --fake) it uses the deterministic offline FakeLLM (no API calls, no cost). Like
the seeder this script commits. Afterward run `make embeddings` (then `make centroids`)
so the new posts get embeddings.
"""

from __future__ import annotations

import argparse
import asyncio

from foryou.config import settings
from foryou.db.session import SessionLocal
from foryou.personas import FakeLLM, LLMClient, OpenAIClient, generate_personas
from foryou.personas.generator import PersonaGenConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate LLM persona content.")
    parser.add_argument(
        "--posts-per-persona", type=int, default=PersonaGenConfig.posts_per_persona
    )
    parser.add_argument(
        "--engagements-per-user", type=int, default=PersonaGenConfig.engagements_per_user
    )
    parser.add_argument("--seed", type=int, default=PersonaGenConfig.seed)
    parser.add_argument(
        "--max-posts",
        type=int,
        default=settings.persona_posts_per_run,
        help="Hard cap on posts inserted this run.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=settings.persona_tokens_per_run,
        help="Hard cap on tokens spent this run.",
    )
    parser.add_argument("--temperature", type=float, default=settings.persona_temperature)
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


async def main() -> None:
    args = build_parser().parse_args()
    config = PersonaGenConfig(
        posts_per_persona=args.posts_per_persona,
        engagements_per_user=args.engagements_per_user,
        seed=args.seed,
        temperature=args.temperature,
        max_posts=args.max_posts,
        max_tokens=args.max_tokens,
    )
    client = _make_client(args.fake)
    async with SessionLocal() as session:
        summary = await generate_personas(session, client, config)
        await session.commit()
    capped = " [CAPPED]" if summary.capped else ""
    print(
        f"generated: {summary.posts_inserted} posts "
        f"({summary.posts_rejected} rejected), {summary.engagements} engagements, "
        f"{summary.tokens_used} tokens (~${summary.estimated_usd:.4f}){capped} "
        f"[model={client.model_version}]"
    )


if __name__ == "__main__":
    asyncio.run(main())
