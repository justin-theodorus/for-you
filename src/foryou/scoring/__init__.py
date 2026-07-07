"""Trained scoring model (plan.md §3): offline training + the artifact serving reads.

``model`` is pure (no sklearn) and safe on the request path; ``dataset`` and ``trainer``
are the offline pipeline that produces the artifact from the engagement log.
"""

from __future__ import annotations

from foryou.scoring.dataset import DatasetConfig, TrainingData, build_training_data
from foryou.scoring.model import (
    FEATURE_NAMES,
    ActionModel,
    ScoringModel,
    features_to_vector,
)
from foryou.scoring.trainer import DEFAULT_MODEL_VERSION, train

__all__ = [
    "DEFAULT_MODEL_VERSION",
    "FEATURE_NAMES",
    "ActionModel",
    "DatasetConfig",
    "ScoringModel",
    "TrainingData",
    "build_training_data",
    "features_to_vector",
    "train",
]
