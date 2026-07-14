"""Shared request dependencies for the ranking API."""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import settings
from foryou.db.models import User
from foryou.db.session import get_session
from foryou.embeddings import Encoder, SentenceTransformerEncoder
from foryou.personas import FakeLLM, LLMClient, OpenAIClient

# The request-scoped DB session, as a reusable FastAPI dependency (Annotated form avoids
# a Depends() call in argument defaults).
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@lru_cache(maxsize=1)
def get_encoder() -> Encoder:
    """Process-wide encoder for the live-trigger path (plan.md §8).

    Cached because the sentence-transformers model costs seconds to load and megabytes to
    hold; the encoder itself defers the torch import to the first ``encode`` call, so an API
    process that never publishes a post never pays for it.
    """
    return SentenceTransformerEncoder()


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    """Process-wide LLM client. No ``OPENAI_API_KEY`` -> the deterministic offline FakeLLM.

    Mirrors ``scripts/generate_personas.py:_make_client`` so the API and the CLIs pick the
    same client, and the live path stays fully exercisable with no key and no spend.
    """
    if not settings.openai_api_key:
        return FakeLLM()
    return OpenAIClient(api_key=settings.openai_api_key)


EncoderDep = Annotated[Encoder, Depends(get_encoder)]
LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]


async def resolve_viewer(
    session: AsyncSession, handle: str | None, user_id: uuid.UUID | None
) -> User:
    """Resolve the feed's viewer by id, then handle, else the first real reader.

    Mirrors ``scripts/rank_feed.py:_resolve_user`` so the API and CLI pick the same
    default user. Raises 404 when nothing matches (usually an unseeded world).
    """
    if user_id is not None:
        user = await session.get(User, user_id)
    elif handle:
        user = await session.scalar(select(User).where(User.handle == handle))
    else:
        user = await session.scalar(
            select(User).where(User.is_persona.is_(False)).order_by(User.handle).limit(1)
        )
    if user is None:
        raise HTTPException(status_code=404, detail="user not found — seed the world first")
    return user
