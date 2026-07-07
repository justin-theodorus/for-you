"""Application configuration loaded from the environment."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The fixed embedding dimension for all pgvector columns. Driven by the local
# sentence-transformers model (all-MiniLM-L6-v2). It must stay constant because
# the HNSW indexes are built against a fixed-width vector column.
EMBEDDING_DIM = 384


class Settings(BaseSettings):
    """Environment-backed settings for the data layer."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://foryou:foryou@localhost:5432/foryou",
        description="Async SQLAlchemy URL (asyncpg) used by the app / ranking service.",
    )
    alembic_database_url: str = Field(
        default="postgresql+psycopg://foryou:foryou@localhost:5432/foryou",
        description="Sync SQLAlchemy URL (psycopg) used only by Alembic migrations.",
    )
    sql_echo: bool = Field(
        default=False,
        description="Echo emitted SQL for debugging.",
    )


settings = Settings()
