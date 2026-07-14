"""Daily budget ledger for the bounded live-trigger path (plan.md §8).

Written through :mod:`foryou.budget`: the batch persona generator (§6) adds tokens, and the
live-trigger path (§8) adds tokens *and* reactions, then reads this row back before every
trigger and short-circuits to "no new reaction" once a cap is hit.

The day key is the real UTC date, not the simulated corpus clock — these counters cap real
API spend, so they reset on real calendar days.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Date, Integer
from sqlalchemy.orm import Mapped, mapped_column

from foryou.db.base import Base
from foryou.db.mixins import updated_at


class BudgetLedger(Base):
    """One row per day tracking spent tokens and persona reactions."""

    __tablename__ = "budget_ledger"

    day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reactions_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = updated_at()
