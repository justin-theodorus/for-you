"""Read-only endpoints backing the demo shell: viewers, topics, pipeline docs, profiles,
trends, and the persisted-impression audit read."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from foryou.candidates import RankingContext, resolve_now
from foryou.candidates.sources import TrendingSource
from foryou.candidates.types import DEFAULT_WEIGHT_VECTOR
from foryou.db.models import FeedImpression, Follow, Post, TopicCentroid, User
from foryou.web import serialize
from foryou.web.deps import SessionDep, resolve_viewer
from foryou.web.schemas import (
    ImpressionView,
    PipelineStageDoc,
    ProfileView,
    TrendItem,
    UserSummary,
)

router = APIRouter(tags=["meta"])

# How many recent posts a profile peek returns.
PROFILE_RECENT_POSTS = 20
# Default trending items surfaced by the trends panel.
TRENDS_LIMIT = 10

# Static description of the pipeline stages for the "how it works" inspector panel.
_PIPELINE_STAGES: list[PipelineStageDoc] = [
    PipelineStageDoc(
        key="sources",
        title="Sources",
        description="Three candidate generators run in parallel: in-network (recent posts "
        "by people you follow), out-of-network (pgvector similarity to your engagement "
        "history), and trending (most-engaged posts in a recent window).",
    ),
    PipelineStageDoc(
        key="merge",
        title="Merge & dedupe",
        description="The three source lists are unioned; a post surfaced by multiple "
        "sources keeps all of its provenance tags but appears once.",
    ),
    PipelineStageDoc(
        key="hydrate",
        title="Hydrate",
        description="One batched query loads post content, counters, topics, and "
        "embeddings, then assembles the five ranking features per candidate.",
    ),
    PipelineStageDoc(
        key="filter",
        title="Filter",
        description="Drops your own posts and anything from blocked/muted accounts.",
    ),
    PipelineStageDoc(
        key="score",
        title="Score",
        description="A trained per-action logistic model predicts like/reply/repost/quote/"
        "dwell probabilities; a weighted sum, times the preference multiplier, is the score.",
    ),
    PipelineStageDoc(
        key="select",
        title="Diversify & select",
        description="MMR greedily picks each slot, trading relevance against similarity to "
        "already-picked posts. The exploration slider is its lambda.",
    ),
    PipelineStageDoc(
        key="log",
        title="Log impression",
        description="Every selected post's source, scores, weights, and penalty are "
        "written to feed_impressions — the sole backing for this panel.",
    ),
]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/users", response_model=list[UserSummary])
async def list_users(session: SessionDep) -> list[UserSummary]:
    """Selectable feed viewers — real readers first, then personas."""
    rows = (
        await session.execute(
            select(User).order_by(User.is_persona, User.handle).limit(100)
        )
    ).scalars().all()
    return [
        UserSummary(
            id=user.id,
            handle=user.handle,
            display_name=user.display_name,
            is_persona=user.is_persona,
            archetype=user.archetype.value if user.archetype is not None else None,
        )
        for user in rows
    ]


@router.get("/topics", response_model=list[str])
async def list_topics(session: SessionDep) -> list[str]:
    """Topics with a centroid — the only ones the topic sliders can steer (plan.md §4)."""
    rows = (
        await session.execute(select(TopicCentroid.topic).order_by(TopicCentroid.topic))
    ).scalars().all()
    return list(rows)


@router.get("/pipeline", response_model=list[PipelineStageDoc])
async def describe_pipeline() -> list[PipelineStageDoc]:
    return _PIPELINE_STAGES


@router.get("/profile/{handle}", response_model=ProfileView)
async def get_profile(
    handle: str, session: SessionDep
) -> ProfileView:
    user = await resolve_viewer(session, handle, None)
    follower_count = await session.scalar(
        select(func.count()).select_from(Follow).where(Follow.followee_id == user.id)
    )
    following_count = await session.scalar(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user.id)
    )
    post_count = await session.scalar(
        select(func.count()).select_from(Post).where(Post.author_id == user.id)
    )
    recent = (
        await session.execute(
            select(Post)
            .where(Post.author_id == user.id)
            .order_by(Post.created_at.desc())
            .limit(PROFILE_RECENT_POSTS)
        )
    ).scalars().all()
    return ProfileView(
        user=serialize.author_view(user),
        follower_count=follower_count or 0,
        following_count=following_count or 0,
        post_count=post_count or 0,
        recent_posts=[serialize.post_summary(post) for post in recent],
    )


@router.get("/trends", response_model=list[TrendItem])
async def get_trends(
    session: SessionDep, limit: int = TRENDS_LIMIT
) -> list[TrendItem]:
    """Top trending posts, reusing the pipeline's own ``TrendingSource`` aggregation."""
    ctx = RankingContext(
        user_id=uuid.uuid4(),  # unused by TrendingSource; it aggregates globally
        now=await resolve_now(session),
        request_id="trends",
        limit=limit,
        user_topics=(),
        followee_ids=frozenset(),
        user_interest_vector=None,
        weight_vector=DEFAULT_WEIGHT_VECTOR,
    )
    candidates = await TrendingSource(limit=limit).fetch(session, ctx)
    if not candidates:
        return []

    post_ids = [candidate.post_id for candidate in candidates]
    post_rows = (
        await session.execute(select(Post).where(Post.id.in_(post_ids)))
    ).scalars().all()
    posts = {post.id: post for post in post_rows}

    author_ids = {post.author_id for post in posts.values()}
    author_rows = (
        await session.execute(select(User).where(User.id.in_(author_ids)))
    ).scalars().all()
    authors = {user.id: user for user in author_rows}

    items: list[TrendItem] = []
    for candidate in candidates:
        post = posts.get(candidate.post_id)
        if post is None:
            continue
        author = authors.get(post.author_id)
        if author is None:
            continue
        velocity = candidate.sources[0].score if candidate.sources else 0.0
        items.append(serialize.trend_item(post, author, velocity))
    return items


@router.get("/impressions/{request_id}", response_model=list[ImpressionView])
async def get_impressions(
    request_id: str, session: SessionDep
) -> list[ImpressionView]:
    """Read back the persisted audit rows for a feed request (logged, not re-derived)."""
    rows = (
        await session.execute(
            select(FeedImpression)
            .where(FeedImpression.request_id == request_id)
            .order_by(FeedImpression.rank)
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="no impressions for that request_id")
    return [serialize.impression_view(row) for row in rows]
