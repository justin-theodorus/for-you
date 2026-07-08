"""Application configuration loaded from the environment."""

from __future__ import annotations

from pathlib import Path

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
    embedding_model_name: str = Field(
        default="all-MiniLM-L6-v2",
        description="sentence-transformers model used to embed posts; also stored as "
        "post_embeddings.model_version. Bump when weights/preprocessing change.",
    )
    embedding_batch_size: int = Field(
        default=128,
        description="Posts encoded and upserted per batch during embedding backfill.",
    )

    # --- Candidate pipeline knobs (plan.md §2). Per-source caps bound how many raw
    # candidates each source contributes before hydration/scoring. ---
    in_network_lookback_days: int = Field(
        default=14,
        description="In-network source only considers followee posts this recent.",
    )
    in_network_limit: int = Field(
        default=200,
        description="Max in-network (followee-recency) candidates per request.",
    )
    out_of_network_limit: int = Field(
        default=200,
        description="Max out-of-network (embedding-similarity) candidates per request.",
    )
    trending_window_hours: int = Field(
        default=48,
        description="Trending source counts engagements within this window off the "
        "reference clock.",
    )
    trending_limit: int = Field(
        default=100,
        description="Max trending (engagement-velocity) candidates per request.",
    )
    recency_half_life_hours: float = Field(
        default=24.0,
        description="Half-life of the recency decay feature (hours).",
    )
    feed_limit: int = Field(
        default=50,
        description="Default number of posts returned in a ranked feed.",
    )

    # --- Diversification (plan.md §5). MMR trades relevance for dissimilarity from the
    # already-selected feed; the live preference slider (plan.md §4) overrides it later. ---
    mmr_lambda: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Relevance weight for MMR diversification in [0,1]. 1.0 = pure "
        "relevance (no diversification); lower = more topical diversity / exploration. "
        "Overridable per request; the live preference slider (plan.md §4) sets it later.",
    )

    # --- Scoring model (plan.md §3). The artifact is produced offline by `make train`
    # and read on the serving path; a missing file falls back to the heuristic scorer. ---
    scoring_model_path: Path = Field(
        default=Path("models/scoring_model.json"),
        description="Where the trained scoring model JSON artifact is written / loaded from.",
    )
    scoring_negative_ratio: float = Field(
        default=3.0,
        description="Sampled non-engaged (user, post) negatives per positive during training.",
    )
    scoring_seed: int = Field(
        default=42,
        description="Seed for deterministic negative sampling in the training set.",
    )

    # --- Web layer (plan.md §9). CORS origins the FastAPI ranking service accepts; the
    # Vite dev server runs on 5173. Set CORS_ORIGINS in .env as a JSON array to override. ---
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"],
        description="Allowed browser origins for the ranking API (JSON array in env).",
    )


settings = Settings()
