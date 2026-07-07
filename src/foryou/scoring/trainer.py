"""Fit the per-action logistic models — the only module that imports scikit-learn.

Each scored action gets an independent binary ``LogisticRegression`` over standardized
features, then the standardizer is *folded into* the linear weights so the saved model is
a plain ``sigmoid(w·x + b)`` with no scaling state to carry at serve time. sklearn is
imported lazily inside :func:`train` so the serving path never pulls it in.

Rare actions can leave a column single-class after negative sampling (``quote`` fires on
~3% of engagements); ``LogisticRegression.fit`` rejects that, so those actions fall back
to a bias-only model carrying just the base rate.
"""

from __future__ import annotations

import datetime
import math

from foryou.candidates.types import ACTION_KEYS
from foryou.scoring.dataset import TrainingData
from foryou.scoring.model import FEATURE_NAMES, ActionModel, ScoringModel

DEFAULT_MODEL_VERSION = "logreg-v1"

# Clamp base rates away from 0/1 so the bias-only logit stays finite.
_RATE_CLAMP = 1e-6


def _bias_only(n_pos: int, n_neg: int) -> ActionModel:
    """A weightless model that predicts the constant base rate (single-class fallback)."""
    total = n_pos + n_neg
    rate = n_pos / total if total else 0.0
    rate = min(max(rate, _RATE_CLAMP), 1.0 - _RATE_CLAMP)
    bias = math.log(rate / (1.0 - rate))
    return ActionModel(
        weights=tuple(0.0 for _ in FEATURE_NAMES),
        bias=bias,
        n_pos=n_pos,
        n_neg=n_neg,
        roc_auc=None,
        log_loss=None,
    )


def _fold_scaler(
    coef: list[float], intercept: float, mean: list[float], scale: list[float]
) -> tuple[tuple[float, ...], float]:
    """Fold ``(x - mean) / scale`` standardization into raw-feature weights + bias.

    ``logit = w·(x - μ)/σ + b = (w/σ)·x + (b - Σ wμ/σ)``. sklearn already sets ``scale_ = 1``
    for zero-variance features, but we guard again to be explicit.
    """
    weights: list[float] = []
    bias = intercept
    for w, mu, sigma in zip(coef, mean, scale, strict=True):
        safe_sigma = sigma or 1.0
        weights.append(w / safe_sigma)
        bias -= w * mu / safe_sigma
    return tuple(weights), bias


def train(
    data: TrainingData,
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    random_state: int = 42,
    trained_at: str | None = None,
) -> ScoringModel:
    """Fit one folded logistic model per action and return the assembled artifact."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    stamp = trained_at or datetime.datetime.now(datetime.UTC).isoformat()
    actions: dict[str, ActionModel] = {}

    for action_index, action in enumerate(ACTION_KEYS):
        labels = [row[action_index] for row in data.y]
        n_pos = sum(labels)
        n_neg = len(labels) - n_pos
        if n_pos == 0 or n_neg == 0:
            actions[action] = _bias_only(n_pos, n_neg)
            continue

        scaler = StandardScaler()
        x_std = scaler.fit_transform(data.x)
        clf = LogisticRegression(
            class_weight="balanced", random_state=random_state, max_iter=1000
        )
        clf.fit(x_std, labels)

        weights, bias = _fold_scaler(
            clf.coef_[0].tolist(),
            float(clf.intercept_[0]),
            scaler.mean_.tolist(),
            scaler.scale_.tolist(),
        )
        # In-sample metrics — enough to audit a small synthetic model, not a held-out eval.
        probs = clf.predict_proba(x_std)[:, 1]
        actions[action] = ActionModel(
            weights=weights,
            bias=bias,
            n_pos=n_pos,
            n_neg=n_neg,
            roc_auc=float(roc_auc_score(labels, probs)),
            log_loss=float(log_loss(labels, probs, labels=[0, 1])),
        )

    return ScoringModel(
        actions=actions,
        feature_names=FEATURE_NAMES,
        model_version=model_version,
        trained_at=stamp,
    )
