"""The feed endpoint — the live, explainable heart of the demo (plan.md §9).

Runs ``rank_feed`` through a traced pipeline, persists the impression audit rows, and
returns the ranked feed with per-post explainability plus the per-request pipeline trace.
Moving a preference slider re-POSTs here and re-ranks for real.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates import rank_feed
from foryou.db.models import Post, User
from foryou.web import serialize
from foryou.web.deps import SessionDep, resolve_viewer
from foryou.web.schemas import FeedRequest, FeedResponse
from foryou.web.trace import build_traced_pipeline

router = APIRouter(tags=["feed"])


async def _load_posts(session: AsyncSession, post_ids: list[uuid.UUID]) -> dict[uuid.UUID, Post]:
    if not post_ids:
        return {}
    rows = (await session.execute(select(Post).where(Post.id.in_(post_ids)))).scalars().all()
    return {post.id: post for post in rows}


async def _load_authors(
    session: AsyncSession, author_ids: set[uuid.UUID]
) -> dict[uuid.UUID, User]:
    if not author_ids:
        return {}
    rows = (await session.execute(select(User).where(User.id.in_(author_ids)))).scalars().all()
    return {user.id: user for user in rows}


@router.post("/feed", response_model=FeedResponse)
async def get_feed(body: FeedRequest, session: SessionDep) -> FeedResponse:
    viewer = await resolve_viewer(session, body.handle, body.user_id)
    preferences = body.preferences.to_preferences() if body.preferences else None
    request_id = str(uuid.uuid4())

    traced, trace = build_traced_pipeline()
    candidates = await rank_feed(
        session,
        viewer.id,
        request_id=request_id,
        limit=body.limit,
        preferences=preferences,
        pipeline=traced,
    )
    # Persist the impression rows the logger wrote so /api/impressions can read them back.
    await session.commit()

    posts = await _load_posts(session, [c.post_id for c in candidates])
    authors = await _load_authors(
        session, {c.author_id for c in candidates if c.author_id is not None}
    )
    model_version = getattr(traced.scorer, "model_version", None)
    return serialize.feed_response(
        viewer,
        candidates,
        preferences,
        trace,
        posts,
        authors,
        request_id=request_id,
        limit=body.limit,
        model_version=model_version,
    )
