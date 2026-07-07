"""Daily budget ledger for the bounded live-trigger path.

Forward-looking: the live-trigger path (later slice) increments these counters
and short-circuits once a hard daily cap is hit.
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
