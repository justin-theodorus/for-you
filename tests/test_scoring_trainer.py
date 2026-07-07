"""Unit tests for the sklearn trainer (runs in Docker where the `train` extra is installed)."""

from __future__ import annotations

from foryou.candidates.types import ACTION_KEYS
from foryou.scoring.dataset import TrainingData
from foryou.scoring.model import FEATURE_NAMES
from foryou.scoring.trainer import train

_LIKE = ACTION_KEYS.index("like")
_REPLY = ACTION_KEYS.index("reply")
_AFFINITY = FEATURE_NAMES.index("author_affinity")


def _row(affinity: float, like: int, reply: int = 0) -> tuple[list[float], list[int]]:
    features = [0.0] * len(FEATURE_NAMES)
    features[_AFFINITY] = affinity
    label = [0] * len(ACTION_KEYS)
    label[_LIKE] = like
    label[_REPLY] = reply
    return features, label


def _separable_data() -> TrainingData:
    # author_affinity = 1 -> liked, 0 -> not; reply never fires (single-class column).
    rows = [_row(1.0, like=1) for _ in range(20)] + [_row(0.0, like=0) for _ in range(20)]
    return TrainingData(x=[f for f, _ in rows], y=[y for _, y in rows], feature_names=FEATURE_NAMES)


def test_trained_like_model_separates_the_classes() -> None:
    model = train(_separable_data(), trained_at="2026-07-01T00:00:00+00:00")

    like = model.actions["like"]
    high = like.probability([1.0 if i == _AFFINITY else 0.0 for i in range(len(FEATURE_NAMES))])
    low = like.probability([0.0] * len(FEATURE_NAMES))

    assert high > low
    assert like.roc_auc is not None and like.roc_auc > 0.9
    assert like.n_pos == 20 and like.n_neg == 20


def test_single_class_action_falls_back_to_bias_only_without_crashing() -> None:
    model = train(_separable_data(), trained_at="2026-07-01T00:00:00+00:00")

    reply = model.actions["reply"]  # reply label was 0 everywhere
    assert reply.weights == tuple(0.0 for _ in FEATURE_NAMES)
    assert reply.roc_auc is None
    assert reply.n_pos == 0
    # Bias-only predicts the (near-zero) base rate regardless of features.
    assert reply.probability([1.0] * len(FEATURE_NAMES)) < 0.5


def test_constant_feature_does_not_break_the_scaler_fold() -> None:
    # engagement_velocity is constant across all rows -> zero variance column.
    data = _separable_data()
    model = train(data, trained_at="2026-07-01T00:00:00+00:00")

    like = model.actions["like"]
    velocity_index = FEATURE_NAMES.index("engagement_velocity")
    assert all(w == w for w in like.weights)  # no NaN
    assert like.weights[velocity_index] == 0.0  # constant feature contributes nothing
