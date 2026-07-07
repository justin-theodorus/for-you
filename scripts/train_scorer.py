"""Train the scoring model on the synthetic engagement log and write the JSON artifact.

Reads the corpus, builds per-user (features, action-label) rows, fits one folded logistic
model per action, and saves the model. Run inside Docker after seeding + embedding:

    docker compose run --rm app python scripts/train_scorer.py --negative-ratio 3

Requires a seeded + embedded corpus (make seed && make embeddings). Reads only; the model
is written to disk (settings.scoring_model_path), never to the DB.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from foryou.config import settings
from foryou.db.session import SessionLocal
from foryou.scoring import DatasetConfig, build_training_data, train
from foryou.scoring.dataset import UserFilter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train the For You scoring model.")
    parser.add_argument(
        "--negative-ratio",
        type=float,
        default=settings.scoring_negative_ratio,
        help="Sampled negatives per positive.",
    )
    parser.add_argument(
        "--users",
        choices=("all", "readers", "personas"),
        default="all",
        help="Which users' engagements to train on.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=settings.scoring_seed,
        help="Seed for deterministic negative sampling.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=settings.scoring_model_path,
        help="Where to write the model JSON artifact.",
    )
    return parser


def _print_metrics(
    model_version: str, actions_metrics: list[tuple[str, int, int, float | None]]
) -> None:
    print(f"trained scoring model (model_version={model_version}):")
    for action, n_pos, n_neg, roc_auc in actions_metrics:
        auc = "n/a" if roc_auc is None else f"{roc_auc:.3f}"
        print(f"  {action:<7} n_pos={n_pos:<4} n_neg={n_neg:<5} roc_auc={auc}")


async def main() -> None:
    args = build_parser().parse_args()
    users: UserFilter = args.users
    config = DatasetConfig(negative_ratio=args.negative_ratio, seed=args.seed, users=users)

    async with SessionLocal() as session:
        data = await build_training_data(session, config)

    if not data.x:
        raise SystemExit(
            "no training examples — seed and embed the world first (make seed && make embeddings)"
        )

    model = train(data)
    model.save(args.out)
    _print_metrics(
        model.model_version,
        [(action, m.n_pos, m.n_neg, m.roc_auc) for action, m in model.actions.items()],
    )
    print(f"\nwrote {args.out} ({len(data.x)} training rows)")


if __name__ == "__main__":
    asyncio.run(main())
