"""FastAPI application factory for the ranking service (plan.md §9)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from foryou.config import settings
from foryou.web.routers import actions, feed, meta

# The SPA the `web` Docker stage builds, copied into the serving image. Absent in local dev
# (where Vite serves it on :5173) and in tests, so the mount below is guarded on it.
SPA_DIR = Path(__file__).resolve().parents[3] / "web" / "dist"


def _mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend from the API, same-origin.

    Same origin is the whole reason CORS and the X-Operator-Secret preflight are non-issues
    in production.
    """
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        # Registering after the routers only protects the API paths that *exist* — this
        # catch-all still matches any shape, so an unmatched /api/* would silently answer
        # index.html with a 200 and turn a client bug into a JSON parse error. Keep the
        # API's 404s real; everything else is client-side routing, so it gets the shell.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(dist / "index.html")


def create_app() -> FastAPI:
    """Build the ranking API: CORS for the Vite dev server, the routers under /api, and
    (in the production image only) the built SPA."""
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

    if (SPA_DIR / "index.html").is_file():
        _mount_spa(app, SPA_DIR)
    return app


app = create_app()
