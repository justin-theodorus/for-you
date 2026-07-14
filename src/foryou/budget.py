"""The daily LLM budget ledger — read, enforce, record (plan.md §8).

One row per wall-clock UTC day in ``budget_ledger``, counting tokens spent and persona
reactions triggered. Two writers share it: the batch persona generator (plan.md §6, tokens
only) and the live-trigger path (plan.md §8, tokens + reactions), so there is exactly one
place that knows how spend is accounted.

The day key is deliberately **wall-clock**, not the simulated corpus clock
(``resolve_now`` / ``BASE_TIME``): these caps bound real API spend, so they must reset on
real calendar days regardless of where the synthetic world's timeline has drifted to.

``load_budget(for_update=True)`` takes a row lock so a check-then-generate sequence can't
overrun the cap under concurrent requests. The lock is therefore held across the LLM call —
acceptable at this scale, and the honest trade for a cap that actually holds; an optimistic
reserve-then-reconcile scheme would be the move if the trigger ever ran hot.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import settings
from foryou.db.models import BudgetLedger


@dataclass(frozen=True, slots=True)
class DailyBudget:
    """Today's spend against today's caps."""

    day: datetime.date
    tokens_used: int
    reactions_used: int
    tokens_cap: int
    reactions_cap: int

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.tokens_cap - self.tokens_used)

    @property
    def reactions_remaining(self) -> int:
        return max(0, self.reactions_cap - self.reactions_used)

    @property
    def exhausted(self) -> bool:
        """True when no further reaction could be generated today."""
        return self.reactions_remaining <= 0 or self.tokens_remaining <= 0


def today() -> datetime.date:
    """The ledger's day key: the real UTC date (never the simulated corpus clock)."""
    return datetime.datetime.now(datetime.UTC).date()


async def load_budget(session: AsyncSession, *, for_update: bool = False) -> DailyBudget:
    """Read today's ledger row, creating it if absent.

    With ``for_update`` the row is locked for the caller's transaction, serializing
    concurrent live triggers so the daily cap can't be overrun by a race between the
    "may I spend?" read and the "I spent" write.
    """
    day = today()
    # Insert-if-absent first: FOR UPDATE can only lock a row that exists.
    await session.execute(
        pg_insert(BudgetLedger).values(day=day).on_conflict_do_nothing(
            index_elements=[BudgetLedger.day]
        )
    )
    stmt = select(BudgetLedger).where(BudgetLedger.day == day)
    if for_update:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalar_one()
    return DailyBudget(
        day=day,
        tokens_used=row.tokens_used,
        reactions_used=row.reactions_used,
        tokens_cap=settings.live_daily_token_cap,
        reactions_cap=settings.live_daily_reaction_cap,
    )


async def record_spend(session: AsyncSession, *, tokens: int, reactions: int = 0) -> None:
    """Add today's spend to the ledger (idempotent upsert on the ``day`` primary key).

    Both counters accumulate. Tokens are counted for *every* LLM attempt, including ones
    the safety gate later rejected — a rejected generation still cost money.
    """
    if tokens <= 0 and reactions <= 0:
        return
    stmt = pg_insert(BudgetLedger).values(
        day=today(), tokens_used=tokens, reactions_used=reactions
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[BudgetLedger.day],
        set_={
            "tokens_used": BudgetLedger.tokens_used + stmt.excluded.tokens_used,
            "reactions_used": BudgetLedger.reactions_used + stmt.excluded.reactions_used,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    await session.flush()
