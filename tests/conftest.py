"""Shared test fixtures.

Each test gets its own ``NullPool`` engine bound to the running event loop (so
pytest-asyncio's per-test loop never tears down a pooled connection from another
loop), and runs inside an outer transaction that is rolled back on teardown. Tests
use ``flush()`` (not ``commit()``) to trigger constraint checks against the live
schema without mutating the database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from foryou.budget import today
from foryou.config import settings
from foryou.db.models import BudgetLedger


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            # create_savepoint so code under test that calls commit() (e.g. the
            # per-batch embedding backfill) releases a SAVEPOINT rather than the
            # outer transaction, keeping the rollback-on-teardown isolation intact.
            db = AsyncSession(
                bind=conn,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                # budget_ledger has no FK to users, so a row committed by a prior
                # `make live` / `make personas` survives the TRUNCATE users CASCADE that
                # `make test-clean` runs — and would silently skew every absolute
                # token/reaction assertion. Clear today's row inside the transaction;
                # the rollback below puts it back.
                await db.execute(delete(BudgetLedger).where(BudgetLedger.day == today()))
                await db.flush()
                yield db
            finally:
                await db.close()
                # A failed flush (constraint-violation tests) aborts the
                # transaction server-side; only roll back if still active.
                if trans.is_active:
                    await trans.rollback()
    finally:
        await engine.dispose()
