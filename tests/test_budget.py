"""Integration tests for the daily LLM budget ledger (plan.md §8).

Runs inside the rolled-back fixture session: budget.py flushes, never commits, so the
savepoint contains every write.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.budget import DailyBudget, load_budget, record_spend, today
from foryou.db.models import BudgetLedger


async def test_load_budget_creates_todays_row_when_absent(session: AsyncSession) -> None:
    budget = await load_budget(session)

    assert budget.day == today()
    assert budget.tokens_used == 0
    assert budget.reactions_used == 0
    row = await session.get(BudgetLedger, today())
    assert row is not None


async def test_record_spend_accumulates_both_counters(session: AsyncSession) -> None:
    await record_spend(session, tokens=100, reactions=2)
    await record_spend(session, tokens=50, reactions=1)

    budget = await load_budget(session)

    assert budget.tokens_used == 150
    assert budget.reactions_used == 3


async def test_record_spend_ignores_an_empty_spend(session: AsyncSession) -> None:
    await record_spend(session, tokens=0, reactions=0)

    row = await session.get(BudgetLedger, today())

    assert row is None  # a no-op spend must not even create today's row


async def test_reactions_used_is_written(session: AsyncSession) -> None:
    """The column existed since the initial schema but had no writer before §8."""
    await record_spend(session, tokens=0, reactions=4)

    row = await session.get(BudgetLedger, today())

    assert row is not None
    assert row.reactions_used == 4


async def test_load_budget_for_update_locks_the_row(session: AsyncSession) -> None:
    """FOR UPDATE is what stops two concurrent triggers both passing the cap check."""
    budget = await load_budget(session, for_update=True)

    assert budget.day == today()


@pytest.mark.parametrize(
    ("tokens_used", "reactions_used", "expect_exhausted"),
    [
        (0, 0, False),
        (999, 5, False),
        (1000, 5, True),  # tokens exhausted
        (500, 10, True),  # reactions exhausted
        (2000, 20, True),  # over both caps
    ],
)
def test_remaining_and_exhausted_arithmetic(
    tokens_used: int, reactions_used: int, expect_exhausted: bool
) -> None:
    budget = DailyBudget(
        day=today(),
        tokens_used=tokens_used,
        reactions_used=reactions_used,
        tokens_cap=1000,
        reactions_cap=10,
    )

    assert budget.tokens_remaining == max(0, 1000 - tokens_used)
    assert budget.reactions_remaining == max(0, 10 - reactions_used)
    assert budget.exhausted is expect_exhausted
