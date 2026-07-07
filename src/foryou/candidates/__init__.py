"""Candidate pipeline: composable Source -> Hydrate -> Filter -> Score -> Select -> log.

Public surface for the ranking service and CLI. Stage classes stay importable from
their modules for custom wiring; ``rank_feed`` / ``default_pipeline`` are the common
entrypoints.
"""

from __future__ import annotations

from foryou.candidates.context import build_context, resolve_now
from foryou.candidates.pipeline import CandidatePipeline, default_pipeline, rank_feed
from foryou.candidates.preferences import NEUTRAL, Preferences
from foryou.candidates.types import (
    ActionScores,
    Candidate,
    Features,
    RankingContext,
    SourceName,
    SourceTag,
)

__all__ = [
    "NEUTRAL",
    "ActionScores",
    "Candidate",
    "CandidatePipeline",
    "Features",
    "Preferences",
    "RankingContext",
    "SourceName",
    "SourceTag",
    "build_context",
    "default_pipeline",
    "rank_feed",
    "resolve_now",
]
