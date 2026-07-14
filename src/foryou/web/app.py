"""FastAPI application factory for the ranking service (plan.md §9)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from foryou.config import settings
from foryou.web.routers import actions, feed, meta


def create_app() -> FastAPI:
    """Build the ranking API: CORS for the Vite dev server, the routers under /api."""
    app = FastAPI(
        title="For You — Ranking API",
        version="0.1.0",
        description="Live, explainable feed ranking over the candidate pipeline (plan.md §9).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(feed.router, prefix="/api")
    app.include_router(actions.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")
    return app


app = create_app()
