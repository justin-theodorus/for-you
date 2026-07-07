"""The trained scoring model as a pure, inspectable artifact.

Deliberately dependency-light — no sklearn, no numpy — so it is safe to import on the
hot serving path. The trainer (``trainer.py``) fits with sklearn and *folds the feature
standardizer into the linear weights*, so serving is a plain ``sigmoid(w·x + b)`` per
action over the five hydrated features.

The JSON on disk is the whole model: five coefficients + a bias per action, plus
provenance (``model_version``, ``trained_at``) and per-action metrics for the audit
panel. ``FEATURE_NAMES`` is the ordering contract shared by training and serving —
``features_to_vector`` is the single place a :class:`Features` becomes an ordered vector,
so the two paths can never silently disagree.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foryou.candidates.types import ACTION_KEYS, Features

# Canonical feature order. This is a contract: the trainer emits weights in this order
# and the scorer reads them in this order. Changing it invalidates every stored artifact
# (guarded by load() below), so bump model_version alongside any change here.
FEATURE_NAMES: tuple[str, ...] = (
    "author_affinity",
    "topic_match",
    "recency",
    "engagement_velocity",
    "embedding_similarity",
)


def features_to_vector(features: Features) -> list[float]:
    """Turn a :class:`Features` into an ordered vector — the single source of truth."""
    return [getattr(features, name) for name in FEATURE_NAMES]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass(frozen=True, slots=True)
class ActionModel:
    """One action's learned linear model (standardizer already folded into ``weights``)."""

    weights: tuple[float, ...]  # len == len(FEATURE_NAMES)
    bias: float
    n_pos: int
    n_neg: int
    roc_auc: float | None  # None when the action had a single class at fit time
    log_loss: float | None

    def probability(self, vector: list[float]) -> float:
        """``sigmoid(w·x + b)`` — the predicted probability of this action."""
        dot = sum(w * x for w, x in zip(self.weights, vector, strict=True))
        return _sigmoid(dot + self.bias)

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": list(self.weights),
            "bias": self.bias,
            "n_pos": self.n_pos,
            "n_neg": self.n_neg,
            "roc_auc": self.roc_auc,
            "log_loss": self.log_loss,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ActionModel:
        weights = tuple(float(w) for w in data["weights"])
        if len(weights) != len(FEATURE_NAMES):
            raise ValueError(
                f"action model has {len(weights)} weights, expected {len(FEATURE_NAMES)}"
            )
        return cls(
            weights=weights,
            bias=float(data["bias"]),
            n_pos=int(data["n_pos"]),
            n_neg=int(data["n_neg"]),
            roc_auc=None if data["roc_auc"] is None else float(data["roc_auc"]),
            log_loss=None if data["log_loss"] is None else float(data["log_loss"]),
        )


@dataclass(frozen=True, slots=True)
class ScoringModel:
    """The full trained model: one :class:`ActionModel` per scored action, plus provenance."""

    actions: Mapping[str, ActionModel]  # keys == ACTION_KEYS
    feature_names: tuple[str, ...]
    model_version: str
    trained_at: str

    def predict_proba(self, vector: list[float]) -> dict[str, float]:
        """Per-action predicted probabilities for one feature vector."""
        return {action: model.probability(vector) for action, model in self.actions.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "trained_at": self.trained_at,
            "feature_names": list(self.feature_names),
            "actions": {action: model.to_dict() for action, model in self.actions.items()},
        }

    def save(self, path: Path) -> None:
        """Write the model as pretty JSON (git-diffable, inspectable — not a pickle)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScoringModel:
        feature_names = tuple(data["feature_names"])
        # Reject any artifact whose feature order or action set drifted from the code —
        # a silent mismatch would score every candidate on the wrong axes.
        if feature_names != FEATURE_NAMES:
            raise ValueError(
                f"artifact feature_names {feature_names} != expected {FEATURE_NAMES}"
            )
        actions = {action: ActionModel.from_dict(data["actions"][action]) for action in ACTION_KEYS}
        return cls(
            actions=actions,
            feature_names=feature_names,
            model_version=str(data["model_version"]),
            trained_at=str(data["trained_at"]),
        )

    @classmethod
    def load(cls, path: Path) -> ScoringModel:
        """Read and validate a model artifact from disk."""
        return cls.from_dict(json.loads(path.read_text()))
