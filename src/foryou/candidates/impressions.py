"""Impression-log side effect — the sole backing for the "Why this post?" panel.

Persists one ``feed_impressions`` row per selected candidate with everything the audit
panel needs (source provenance, per-action scores, active weight vector, penalty,
final score, rank) so the panel renders with no re-derivation. The library flushes;
the caller commits.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.types import Candidate, RankingContext
from foryou.db.models import FeedImpression


class ImpressionLogger:
    """Writes the selected feed to ``feed_impressions``."""

    async def emit(
        self, session: AsyncSession, candidates: list[Candidate], ctx: RankingContext
    ) -> None:
        if not candidates:
            return
        session.add_all(
            [
                FeedImpression(
                    user_id=ctx.user_id,
                    post_id=candidate.post_id,
                    request_id=ctx.request_id,
                    sources=[
                        {"source": tag.source.value, "score": tag.score}
                        for tag in candidate.sources
                    ],
                    action_scores=(
                        candidate.action_scores.as_dict()
                        if candidate.action_scores is not None
                        else {}
                    ),
                    weight_vector=dict(ctx.weight_vector),
                    mmr_penalty=candidate.mmr_penalty,
                    final_score=candidate.score,
                    rank=candidate.rank,
                    scoring_model_version=ctx.scoring_model_version,
                )
                for candidate in candidates
            ]
        )
        await session.flush()
