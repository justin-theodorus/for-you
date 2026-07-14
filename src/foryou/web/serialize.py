"""Pure mappers: pipeline value types + ORM rows -> API schemas.

Kept free of I/O — the routers fetch rows and hand them here. Reuses the domain
types' own JSON views (``ActionScores.as_dict``, ``Preferences.as_dict``) so the API
can't drift from what the pipeline computes and the impression log persists.
"""

from __future__ import annotations

from typing import Any

from foryou.budget import DailyBudget
from foryou.candidates import Candidate, Preferences
from foryou.db.models import FeedImpression, Post, User
from foryou.live import LiveTriggerSummary
from foryou.web.schemas import (
    ActionScoresView,
    AuthorView,
    BudgetStatus,
    FeaturesView,
    FeedItem,
    FeedResponse,
    ImpressionView,
    LivePostResponse,
    PipelineTrace,
    PostSummary,
    ReactionView,
    ScoreStats,
    SourceTagView,
    StageCount,
    TrendItem,
    WhyThisPost,
)
from foryou.web.trace import PipelineTraceData


def author_view(user: User) -> AuthorView:
    return AuthorView(
        id=user.id,
        handle=user.handle,
        display_name=user.display_name,
        is_persona=user.is_persona,
        archetype=user.archetype.value if user.archetype is not None else None,
        bio=user.bio,
    )


def _why_this_post(candidate: Candidate) -> WhyThisPost:
    features = candidate.features
    scores = candidate.action_scores
    return WhyThisPost(
        sources=[
            SourceTagView(source=tag.source.value, score=tag.score)
            for tag in candidate.sources
        ],
        action_scores=(
            ActionScoresView(**scores.as_dict()) if scores is not None else None
        ),
        features=(
            FeaturesView(
                author_affinity=features.author_affinity,
                topic_match=features.topic_match,
                recency=features.recency,
                engagement_velocity=features.engagement_velocity,
                embedding_similarity=features.embedding_similarity,
            )
            if features is not None
            else None
        ),
        preference_multiplier=candidate.preference_multiplier,
        mmr_penalty=candidate.mmr_penalty,
        final_score=candidate.score,
        rank=candidate.rank,
    )


def _feed_item(candidate: Candidate, post: Post, author: AuthorView) -> FeedItem:
    return FeedItem(
        post_id=post.id,
        content=post.content,
        created_at=post.created_at,
        topics=list(post.topics),
        like_count=post.like_count,
        reply_count=post.reply_count,
        repost_count=post.repost_count,
        quote_count=post.quote_count,
        author=author,
        rank=candidate.rank,
        final_score=candidate.score,
        why=_why_this_post(candidate),
    )


def _source_mix(candidates: list[Candidate]) -> list[StageCount]:
    """How many of the *selected* feed carry each source tag (candidates can share)."""
    counts: dict[str, int] = {}
    for candidate in candidates:
        for tag in candidate.sources:
            counts[tag.source.value] = counts.get(tag.source.value, 0) + 1
    return [StageCount(name=name, count=count) for name, count in sorted(counts.items())]


def _score_stats(candidates: list[Candidate]) -> ScoreStats:
    scores = [c.score for c in candidates if c.score is not None]
    if not scores:
        return ScoreStats(min=None, max=None, mean=None)
    return ScoreStats(min=min(scores), max=max(scores), mean=sum(scores) / len(scores))


def pipeline_trace(trace: PipelineTraceData, candidates: list[Candidate]) -> PipelineTrace:
    return PipelineTrace(
        per_source=[
            StageCount(name=name, count=count)
            for name, count in sorted(trace.per_source.items())
        ],
        candidates_total=sum(trace.per_source.values()),
        merged=trace.merged,
        filters=[StageCount(name=name, count=count) for name, count in trace.filters],
        selected=trace.selected,
        source_mix=_source_mix(candidates),
        score_stats=_score_stats(candidates),
        diversified=sum(
            1 for c in candidates if c.mmr_penalty is not None and c.mmr_penalty > 0
        ),
    )


def feed_response(
    viewer: User,
    candidates: list[Candidate],
    preferences: Preferences | None,
    trace: PipelineTraceData,
    posts: dict[Any, Post],
    authors: dict[Any, User],
    *,
    request_id: str,
    limit: int,
    model_version: str | None,
) -> FeedResponse:
    author_views = {uid: author_view(user) for uid, user in authors.items()}
    items = [
        _feed_item(candidate, posts[candidate.post_id], author_views[candidate.author_id])
        for candidate in candidates
        if candidate.post_id in posts and candidate.author_id in author_views
    ]
    return FeedResponse(
        request_id=request_id,
        viewer=author_view(viewer),
        limit=limit,
        model_version=model_version,
        # The vector the run actually collapsed action scores with, captured from the
        # context by the trace. The API exposes no way to set it, so today it is always the
        # uniform default — but reading it back from the run means the panel can never lie.
        # rank_feed(weight_vector=...) remains the seam for offline weight experiments.
        weight_vector=dict(trace.weight_vector),
        preferences=(preferences or Preferences()).as_dict(),
        trace=pipeline_trace(trace, candidates),
        items=items,
    )


def post_summary(post: Post) -> PostSummary:
    return PostSummary(
        post_id=post.id,
        content=post.content,
        created_at=post.created_at,
        topics=list(post.topics),
        like_count=post.like_count,
        reply_count=post.reply_count,
        repost_count=post.repost_count,
        quote_count=post.quote_count,
    )


def trend_item(post: Post, author: User, velocity: float) -> TrendItem:
    return TrendItem(
        post_id=post.id,
        content=post.content,
        author=author_view(author),
        velocity=velocity,
        topics=list(post.topics),
        like_count=post.like_count,
        reply_count=post.reply_count,
        repost_count=post.repost_count,
        quote_count=post.quote_count,
    )


def budget_status(budget: DailyBudget) -> BudgetStatus:
    return BudgetStatus(
        day=budget.day,
        tokens_used=budget.tokens_used,
        tokens_cap=budget.tokens_cap,
        tokens_remaining=budget.tokens_remaining,
        reactions_used=budget.reactions_used,
        reactions_cap=budget.reactions_cap,
        reactions_remaining=budget.reactions_remaining,
        exhausted=budget.exhausted,
    )


def live_post_response(
    post: Post, author: User, summary: LiveTriggerSummary, *, model_version: str
) -> LivePostResponse:
    return LivePostResponse(
        post=post_summary(post),
        author=author_view(author),
        reactions=[
            ReactionView(
                persona_id=reaction.persona_id,
                persona_handle=reaction.persona_handle,
                post_id=reaction.post_id,
                content=reaction.content,
            )
            for reaction in summary.reactions
        ],
        rejected=list(summary.rejected),
        engagements=summary.engagements,
        tokens_used=summary.tokens_used,
        estimated_usd=summary.estimated_usd,
        capped=summary.capped,
        cap_reason=summary.cap_reason,
        model_version=model_version,
        budget=budget_status(summary.budget),
    )


def impression_view(row: FeedImpression) -> ImpressionView:
    return ImpressionView(
        post_id=row.post_id,
        rank=row.rank,
        final_score=row.final_score,
        sources=row.sources,
        action_scores=row.action_scores,
        weight_vector=row.weight_vector,
        preferences=row.preferences,
        preference_multiplier=row.preference_multiplier,
        mmr_penalty=row.mmr_penalty,
        scoring_model_version=row.scoring_model_version,
    )
