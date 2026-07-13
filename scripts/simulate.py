"""Advance the synthetic world by N ticks (batch world generation, plan.md §7).

    docker compose run --rm app python scripts/simulate.py --ticks 6

Additive: run after `make seed`. Authors templated persona posts + heuristic
engagements on a timeline that advances forward from BASE_TIME, then refreshes
post_velocity. No LLM, no cost. Like the seeder this script commits. Afterward run
`make embeddings` (then `make centroids`) so the new posts get embeddings.
"""

from __future__ import annotations

import argparse
import asyncio

from foryou.db.session import SessionLocal
from foryou.simulate import SimulationConfig, simulate_world


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Advance the synthetic world by N ticks.")
    parser.add_argument("--ticks", type=int, default=SimulationConfig.ticks)
    parser.add_argument(
        "--tick-hours",
        type=float,
        default=SimulationConfig.tick_hours,
        help="Simulated hours advanced per tick.",
    )
    parser.add_argument(
        "--posts-per-persona", type=int, default=SimulationConfig.posts_per_persona
    )
    parser.add_argument(
        "--engagements-per-user", type=int, default=SimulationConfig.engagements_per_user
    )
    parser.add_argument("--seed", type=int, default=SimulationConfig.seed)
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    config = SimulationConfig(
        ticks=args.ticks,
        tick_hours=args.tick_hours,
        posts_per_persona=args.posts_per_persona,
        engagements_per_user=args.engagements_per_user,
        seed=args.seed,
    )
    async with SessionLocal() as session:
        summary = await simulate_world(session, config)
        await session.commit()
    if summary.ticks_run == 0:
        print("no personas found — seed the world first (make seed ARGS=\"--wipe\").")
        return
    print(
        f"simulated: {summary.ticks_run} ticks, {summary.posts} posts, "
        f"{summary.engagements} engagements, {summary.velocity_rows} velocity rows "
        f"[{summary.start_at:%Y-%m-%d %H:%M} -> {summary.end_at:%Y-%m-%d %H:%M} UTC]"
    )


if __name__ == "__main__":
    asyncio.run(main())
