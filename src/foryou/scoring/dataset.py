"""Assemble the scoring model's training set from the engagement log.

Train/serve parity is the whole game: features are built with the *same*
:func:`build_context` + :class:`PostHydrator` the live pipeline uses, so a feature can
never mean one thing at fit time and another at request time. Each ``(user, post)`` pair
becomes one row — a five-feature vector plus a five-bit label over the scored actions.

Positives come straight from ``engagements``; negatives are sampled non-engaged posts.
One correction is applied for positives: ``embedding_similarity`` is recomputed
*leave-one-out* — the user's interest vector normally includes the post being scored (it
was engaged), which never happens at serve time, so we subtract the post's own
contribution before measuring similarity.
"""

from __future__ import annotations

import random
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.context import build_context, resolve_now
from foryou.candidates.hydrator import PostHydrator, cosine_similarity
from foryou.candidates.types import ACTION_KEYS, Candidate
from foryou.db.enums import EngagementKind
from foryou.db.models import Engagement, Post, PostEmbedding, User
from foryou.scoring.model import FEATURE_NAMES, features_to_vector

_EMBEDDING_SIMILARITY_INDEX = FEATURE_NAMES.index("embedding_similarity")
UserFilter = Literal["all", "readers", "personas"]


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    """Knobs for training-set construction."""

    negative_ratio: float = 3.0
    seed: int = 42
    users: UserFilter = "all"
    leave_one_out_interest: bool = True


@dataclass(frozen=True, slots=True)
class TrainingData:
    """A matrix of feature vectors and a matrix of per-action labels (both row-aligned)."""

    x: list[list[float]]  # n x len(FEATURE_NAMES)
    y: list[list[int]]  # n x len(ACTION_KEYS), 0/1 per action
    feature_names: tuple[str, ...]


async def _load_users(session: AsyncSession, which: UserFilter) -> list[User]:
    stmt = select(User).order_by(User.handle)
    if which == "readers":
        stmt = stmt.where(User.is_persona.is_(False))
    elif which == "personas":
        stmt = stmt.where(User.is_persona.is_(True))
    return list(await session.scalars(stmt))


async def _load_posts(session: AsyncSession) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Every post's ``(id, author_id)`` — the pool negatives are sampled from."""
    rows = await session.execute(select(Post.id, Post.author_id).order_by(Post.id))
    return [(row[0], row[1]) for row in rows]


async def _engaged_kinds(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[uuid.UUID, set[EngagementKind]]:
    """Map each post the user engaged to the set of engagement kinds on it."""
    rows = await session.execute(
        select(Engagement.post_id, Engagement.kind)
        .where(Engagement.user_id == user_id)
        .order_by(Engagement.post_id)
    )
    kinds: dict[uuid.UUID, set[EngagementKind]] = defaultdict(set)
    for post_id, kind in rows:
        kinds[post_id].add(kind)
    return dict(kinds)


async def _interest_rows(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[uuid.UUID, tuple[float, ...]]]:
    """Post embeddings behind the user's interest vector — mirrors ``context._interest_vector``.

    One row per non-``report`` engagement that has an embedding (a post engaged twice
    appears twice), so the mean here equals ``ctx.user_interest_vector`` exactly. Used to
    subtract a positive post's own contribution for the leave-one-out similarity.
    """
    rows = await session.execute(
        select(Engagement.post_id, PostEmbedding.embedding)
        .join(PostEmbedding, PostEmbedding.post_id == Engagement.post_id)
        .where(
            Engagement.user_id == user_id,
            Engagement.kind != EngagementKind.REPORT,
        )
        .order_by(Engagement.post_id)
    )
    return [(post_id, tuple(float(x) for x in embedding)) for post_id, embedding in rows]


def _label_vector(kinds: set[EngagementKind]) -> list[int]:
    """One bit per scored action; ``click``/``report`` set no bit (not scored actions)."""
    present = {kind.value for kind in kinds}
    return [1 if action in present else 0 for action in ACTION_KEYS]


def _sample(rng: random.Random, pool: list[uuid.UUID], k: int) -> list[uuid.UUID]:
    if k <= 0 or not pool:
        return []
    if k >= len(pool):
        return list(pool)
    return rng.sample(pool, k)


def _loo_means(
    sum_vec: list[float], count: int, per_post: dict[uuid.UUID, list[tuple[float, ...]]]
) -> dict[uuid.UUID, tuple[float, ...] | None]:
    """Interest-vector mean with each positive post's own contributions removed."""
    means: dict[uuid.UUID, tuple[float, ...] | None] = {}
    for post_id, vectors in per_post.items():
        loo_count = count - len(vectors)
        if loo_count <= 0:
            means[post_id] = None  # no other history -> serve-time interest vector is None
            continue
        loo_sum = list(sum_vec)
        for vector in vectors:
            for index, value in enumerate(vector):
                loo_sum[index] -= value
        means[post_id] = tuple(total / loo_count for total in loo_sum)
    return means


async def build_training_data(session: AsyncSession, config: DatasetConfig) -> TrainingData:
    """Build the ``(features, labels)`` matrices for every selected user's engagements."""
    rng = random.Random(config.seed)
    hydrator = PostHydrator()
    now = await resolve_now(session)  # pin the clock once so recency is stable across users
    users = await _load_users(session, config.users)
    all_posts = await _load_posts(session)

    x: list[list[float]] = []
    y: list[list[int]] = []

    for user in users:
        engaged = await _engaged_kinds(session, user.id)
        positives = {
            post_id: kinds
            for post_id, kinds in engaged.items()
            if any(kind is not EngagementKind.REPORT for kind in kinds)
        }
        if not positives:
            continue

        engaged_ids = set(engaged)  # exclude all interactions (incl. report) from negatives
        neg_pool = [
            pid
            for pid, author_id in all_posts
            if author_id != user.id and pid not in engaged_ids
        ]
        negatives = _sample(rng, neg_pool, round(len(positives) * config.negative_ratio))

        ctx = await build_context(session, user.id, now=now)
        candidates = [Candidate(post_id=pid, sources=()) for pid in [*positives, *negatives]]
        hydrated = await hydrator.hydrate(session, candidates, ctx)

        loo_means: dict[uuid.UUID, tuple[float, ...] | None] = {}
        if config.leave_one_out_interest:
            rows = await _interest_rows(session, user.id)
            per_post: dict[uuid.UUID, list[tuple[float, ...]]] = defaultdict(list)
            sum_vec: list[float] = []
            for post_id, embedding in rows:
                per_post[post_id].append(embedding)
                if not sum_vec:
                    sum_vec = [0.0] * len(embedding)
                for index, value in enumerate(embedding):
                    sum_vec[index] += value
            positives_with_history = {pid: per_post[pid] for pid in positives if pid in per_post}
            loo_means = _loo_means(sum_vec, len(rows), positives_with_history)

        for candidate in hydrated:
            assert candidate.features is not None  # hydrate always sets features
            vector = features_to_vector(candidate.features)
            is_positive = candidate.post_id in positives
            if is_positive and candidate.post_id in loo_means and candidate.embedding is not None:
                loo_mean = loo_means[candidate.post_id]
                vector[_EMBEDDING_SIMILARITY_INDEX] = cosine_similarity(
                    candidate.embedding, loo_mean
                )
            if is_positive:
                label = _label_vector(positives[candidate.post_id])
            else:
                label = [0] * len(ACTION_KEYS)
            x.append(vector)
            y.append(label)

    return TrainingData(x=x, y=y, feature_names=FEATURE_NAMES)
