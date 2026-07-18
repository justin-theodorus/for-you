"""Tests for the one-shot deployment bootstrap.

Runs against the rolled-back fixture session with ``FakeEncoder``, so the whole
seed -> embed -> centroids chain is exercised with no torch and no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.bootstrap import (
    BootstrapSummary,
    ScoringArtifactMissing,
    bootstrap,
    world_exists,
)
from foryou.candidates.scoring import HEURISTIC_MODEL_VERSION, default_scorer
from foryou.config import settings
from foryou.db.models import Post, PostEmbedding, TopicCentroid, User
from foryou.scoring.model import ScoringModel
from foryou.seed import SeedConfig
from tests.test_encoder import FakeEncoder

# A small world; the bootstrap's behaviour, not the seeder's, is under test here.
_CONFIG = SeedConfig(
    personas=6,
    readers=2,
    posts_per_persona=4,
    follows_per_user=3,
    engagements_per_user=6,
    seed=11,
)


async def _counts(session: AsyncSession) -> tuple[int, int, int, int]:
    async def count(model: type) -> int:
        return await session.scalar(select(func.count()).select_from(model)) or 0

    return (
        await count(User),
        await count(Post),
        await count(PostEmbedding),
        await count(TopicCentroid),
    )


async def test_bootstrap_populates_an_empty_world(session: AsyncSession) -> None:
    # Arrange
    assert not await world_exists(session)

    # Act
    summary = await bootstrap(session, FakeEncoder(), config=_CONFIG)

    # Assert
    assert summary.skipped is False
    users, posts, embeddings, centroids = await _counts(session)
    assert users == summary.users > 0
    assert posts == summary.posts > 0
    # Every post is embedded, or the out-of-network source has nothing to match on.
    assert embeddings == posts
    # Centroids are asserted off the run's own count, not the table's: topic_centroids has
    # no FK to users, so rows committed by a prior `make seed` survive the TRUNCATE users
    # CASCADE that `make test-clean` runs (the same quirk conftest documents for
    # budget_ledger). The table is therefore a floor, not an equality.
    assert summary.centroids > 0
    assert centroids >= summary.centroids


async def test_bootstrap_is_idempotent(session: AsyncSession) -> None:
    """The skip is what makes the post-deploy one-off safe to re-run."""
    # Arrange
    await bootstrap(session, FakeEncoder(), config=_CONFIG)
    before = await _counts(session)

    # Act
    second = await bootstrap(session, FakeEncoder(), config=_CONFIG)

    # Assert
    assert second == BootstrapSummary(
        skipped=True, users=0, posts=0, embeddings=0, centroids=0
    )
    assert await _counts(session) == before


async def test_force_reseeds_over_an_existing_world(session: AsyncSession) -> None:
    # Arrange
    await bootstrap(session, FakeEncoder(), config=_CONFIG)
    before = await _counts(session)

    # Act
    forced = await bootstrap(session, FakeEncoder(), config=_CONFIG, force=True)

    # Assert: wiped and re-seeded, not appended to (the seeder is deterministic, so the
    # same config yields the same row counts).
    assert forced.skipped is False
    assert await _counts(session) == before


async def test_missing_artifact_fails_loudly_instead_of_seeding(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The artifact check must precede the seed, and must raise rather than warn.

    A silent HeuristicScorer fallback in production is the failure this whole path exists
    to prevent, so the error names the fix.
    """
    # Arrange
    monkeypatch.setattr(settings, "scoring_model_path", Path("models/does_not_exist.json"))

    # Act / Assert
    with pytest.raises(ScoringArtifactMissing, match="make train"):
        await bootstrap(session, FakeEncoder(), config=_CONFIG)
    assert not await world_exists(session)


def test_committed_artifact_loads_and_is_not_the_heuristic() -> None:
    """The test that catches the demo silently shipping an untrained feed.

    ``default_scorer()`` only existence-checks the path and falls back with a log warning,
    so a missing or unparseable artifact is invisible at runtime. Assert the committed file
    is really there, really loads, and really is what the serving path picks.
    """
    # Arrange / Act
    path = settings.scoring_model_path
    assert path.exists(), f"the trained artifact must be committed at {path}"
    model = ScoringModel.load(path)
    scorer = default_scorer()

    # Assert
    assert model.model_version != HEURISTIC_MODEL_VERSION
    assert model.actions, "a trained model must carry per-action weight vectors"
    assert type(scorer).__name__ == "TrainedScorer"
