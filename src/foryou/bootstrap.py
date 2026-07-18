"""One-shot idempotent world bootstrap for a fresh deployment.

A deployed database starts empty, and every rankable thing in this project is derived:
the seeded corpus, its embeddings, and the topic centroids the §4 sliders steer. This
composes the three existing backfills in dependency order behind one idempotent call, so
bringing up a new environment is `python scripts/bootstrap.py` rather than a remembered
four-command sequence.

**It never trains.** The trained artifact (plan.md §3) is committed and baked into the
image, because ``default_scorer()`` falls back to the heuristic *silently* when the file is
missing — a deployment that trained on its own ephemeral disk would look fine and serve the
wrong feed. So this asserts the artifact is present rather than producing one, and the
serving image carries no sklearn. The seeder is deterministic, so the committed model is a
valid model for the world this produces.

Migrations stay out: they are Alembic's job, they run over the sync/psycopg URL, and they
belong in the release command where a failure *should* block the deploy.

Per the repo convention the module only flushes; ``scripts/bootstrap.py`` commits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import settings
from foryou.db.models import User
from foryou.embeddings import Encoder, generate_embeddings, generate_topic_centroids
from foryou.seed import SeedConfig, seed_world

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BootstrapSummary:
    """What a bootstrap run did. ``skipped`` means the world already existed."""

    skipped: bool
    users: int
    posts: int
    embeddings: int
    centroids: int


class ScoringArtifactMissing(RuntimeError):
    """The trained scorer artifact is absent, so the feed would silently degrade."""


async def world_exists(session: AsyncSession) -> bool:
    """Is there already a world here? Cheap, and deliberately checked before any import
    of torch — the skip path on an already-bootstrapped deploy costs a single COUNT."""
    count = await session.scalar(select(func.count()).select_from(User))
    return bool(count)


def require_scoring_artifact() -> None:
    """Fail loudly now rather than serving a heuristic feed that looks trained."""
    path = settings.scoring_model_path
    if not path.exists():
        raise ScoringArtifactMissing(
            f"no trained scoring model at {path}. The artifact is committed to the repo and "
            "baked into the image; if it is missing here, reproduce it with `make train` "
            "(seed -> embeddings -> centroids -> train) and commit the result. Bootstrapping "
            "without it would silently fall back to HeuristicScorer."
        )


async def bootstrap(
    session: AsyncSession,
    encoder: Encoder,
    *,
    config: SeedConfig | None = None,
    force: bool = False,
) -> BootstrapSummary:
    """Seed, embed, and compute centroids — unless a world is already here.

    ``force`` re-seeds over the existing world (``SeedConfig.wipe``); without it an
    existing world short-circuits, which is what makes this safe to re-run.
    """
    require_scoring_artifact()

    if not force and await world_exists(session):
        logger.info("world already present — skipping bootstrap")
        return BootstrapSummary(skipped=True, users=0, posts=0, embeddings=0, centroids=0)

    seed_config = config or SeedConfig()
    if force:
        seed_config = replace(seed_config, wipe=True)

    summary = await seed_world(session, seed_config)
    logger.info("seeded %d users / %d posts", summary.users, summary.posts)

    embeddings = await generate_embeddings(session, encoder)
    logger.info("embedded %d posts", embeddings)

    centroids = await generate_topic_centroids(session)
    logger.info("wrote %d topic centroids", centroids)

    return BootstrapSummary(
        skipped=False,
        users=summary.users,
        posts=summary.posts,
        embeddings=embeddings,
        centroids=centroids,
    )
