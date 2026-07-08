"""Shared request dependencies for the ranking API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.db.models import User
from foryou.db.session import get_session

# The request-scoped DB session, as a reusable FastAPI dependency (Annotated form avoids
# a Depends() call in argument defaults).
SessionDep = Annotated[AsyncSession, Depends(get_session)]


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
