"""Tests for training-set construction from the engagement log."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from foryou.candidates.types import ACTION_KEYS
from foryou.db.enums import EngagementKind
from foryou.scoring.dataset import (
    _EMBEDDING_SIMILARITY_INDEX,
    DatasetConfig,
    _loo_means,
    build_training_data,
)
from foryou.scoring.model import FEATURE_NAMES
from tests.candidate_factories import make_embedding, make_engagement, make_post, make_user

_LIKE = ACTION_KEYS.index("like")


async def test_positive_labels_mark_the_engaged_action_and_exclude_report(
    session: AsyncSession,
) -> None:
    author = await make_user(session, "author", topics=["tech"])
    reader = await make_user(session, "reader", is_persona=False, topics=["tech"])
    liked = await make_post(session, author, topics=["tech"])
    clicked = await make_post(session, author, topics=["tech"])
    reported = await make_post(session, author, topics=["tech"])
    await make_engagement(session, reader, liked, kind=EngagementKind.LIKE)
    await make_engagement(session, reader, clicked, kind=EngagementKind.CLICK)
    await make_engagement(session, reader, reported, kind=EngagementKind.REPORT)

    data = await build_training_data(session, DatasetConfig(users="readers", negative_ratio=0.0))

    # report-only pair is not a positive -> two rows, not three.
    assert len(data.y) == 2
    like_hot = [0] * len(ACTION_KEYS)
    like_hot[_LIKE] = 1
    all_zero = [0] * len(ACTION_KEYS)
    assert sorted(data.y) == sorted([like_hot, all_zero])  # click set no bit


async def test_negatives_exclude_self_authored_and_engaged_posts(session: AsyncSession) -> None:
    author = await make_user(session, "author", topics=["tech"])
    reader = await make_user(session, "reader", is_persona=False, topics=["tech"])
    liked = await make_post(session, author, topics=["tech"])
    reported = await make_post(session, author, topics=["tech"])
    extra_a = await make_post(session, author, topics=["tech"])
    extra_b = await make_post(session, author, topics=["tech"])
    await make_post(session, reader, topics=["tech"])  # reader-authored -> must not be a negative
    await make_engagement(session, reader, liked, kind=EngagementKind.LIKE)
    await make_engagement(session, reader, reported, kind=EngagementKind.REPORT)

    # Large ratio drains the whole eligible negative pool.
    data = await build_training_data(session, DatasetConfig(users="readers", negative_ratio=10.0))

    # 1 positive (liked) + only the two non-engaged author posts (extra_a, extra_b).
    assert len(data.y) == 3
    assert sum(row[_LIKE] for row in data.y) == 1
    assert sum(1 for row in data.y if row == [0] * len(ACTION_KEYS)) == 2
    del extra_a, extra_b


async def test_leave_one_out_changes_positive_embedding_similarity(session: AsyncSession) -> None:
    author = await make_user(session, "author", topics=["tech"])
    reader = await make_user(session, "reader", is_persona=False, topics=["tech"])
    post_a = await make_post(session, author, topics=["tech"])
    post_b = await make_post(session, author, topics=["tech"])
    await make_embedding(session, post_a, bump_index=1)
    await make_embedding(session, post_b, bump_index=200)  # distinct direction
    await make_engagement(session, reader, post_a, kind=EngagementKind.LIKE)
    await make_engagement(session, reader, post_b, kind=EngagementKind.LIKE)

    with_loo = await build_training_data(
        session, DatasetConfig(users="readers", negative_ratio=0.0, leave_one_out_interest=True)
    )
    without_loo = await build_training_data(
        session, DatasetConfig(users="readers", negative_ratio=0.0, leave_one_out_interest=False)
    )

    sims_with = sorted(row[_EMBEDDING_SIMILARITY_INDEX] for row in with_loo.x)
    sims_without = sorted(row[_EMBEDDING_SIMILARITY_INDEX] for row in without_loo.x)
    assert sims_with != sims_without


def test_loo_means_subtracts_the_posts_own_contribution() -> None:
    pa, pb = uuid.uuid4(), uuid.uuid4()
    sum_vec = [2.0, 2.0]  # v1=(1,0) + v2=(0,1) + v3=(1,1)
    per_post: dict[uuid.UUID, list[tuple[float, ...]]] = {
        pa: [(1.0, 0.0)],
        pb: [(1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
    }

    means = _loo_means(sum_vec, count=3, per_post=per_post)

    assert means[pa] == (0.5, 1.0)  # (2-1)/2, (2-0)/2
    assert means[pb] is None  # all history removed -> no leave-one-out mean


def test_feature_names_are_the_dataset_contract() -> None:
    assert FEATURE_NAMES == (
        "author_affinity",
        "topic_match",
        "recency",
        "engagement_velocity",
        "embedding_similarity",
    )
