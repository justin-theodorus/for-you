"""FastAPI ranking service (plan.md §9).

Thin HTTP layer over the candidate pipeline: ``rank_feed`` serves the feed, the
``feed_impressions`` log backs the "Why this post?" panel, and a counting-proxy traced
pipeline (:mod:`foryou.web.trace`) surfaces per-stage candidate flow for the inspector —
all without touching the pipeline core. Served by the ``api`` compose service
(``uvicorn foryou.web.app:app``).
"""

from __future__ import annotations

from foryou.web.app import app, create_app

__all__ = ["app", "create_app"]
