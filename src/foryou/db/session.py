"""Async engine and session factory for the application / ranking service."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from foryou.config import settings

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async session (FastAPI-dependency friendly)."""
    async with SessionLocal() as session:
        yield session
