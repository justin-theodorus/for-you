"""Unit tests for the pure scoring-model artifact (no DB, no sklearn)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from foryou.candidates.types import ACTION_KEYS, Features
from foryou.scoring.model import (
    FEATURE_NAMES,
    ActionModel,
    ScoringModel,
    features_to_vector,
)


def _model(**overrides: ActionModel) -> ScoringModel:
    actions = {
        action: overrides.get(
            action,
            ActionModel(
                weights=tuple(0.0 for _ in FEATURE_NAMES),
                bias=0.0,
                n_pos=1,
                n_neg=1,
                roc_auc=0.5,
                log_loss=0.6,
            ),
        )
        for action in ACTION_KEYS
    }
    return ScoringModel(
        actions=actions,
        feature_names=FEATURE_NAMES,
        model_version="test-v1",
        trained_at="2026-07-01T00:00:00+00:00",
    )


def test_features_to_vector_follows_feature_names_order() -> None:
    features = Features(
        author_affinity=1.0,
        topic_match=2.0,
        recency=3.0,
        engagement_velocity=4.0,
        embedding_similarity=5.0,
    )

    vector = features_to_vector(features)

    assert vector == [getattr(features, name) for name in FEATURE_NAMES]
    assert vector == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_probability_is_sigmoid_of_linear_combination() -> None:
    like = ActionModel(
        weights=(1.0, 0.0, 0.0, 0.0, 0.0), bias=0.5, n_pos=1, n_neg=1, roc_auc=None, log_loss=None
    )
    model = _model(like=like)

    prob = model.predict_proba([2.0, 0.0, 0.0, 0.0, 0.0])["like"]

    assert prob == pytest.approx(1.0 / (1.0 + math.exp(-(1.0 * 2.0 + 0.5))))


def test_save_load_round_trip(tmp_path: Path) -> None:
    model = _model(
        reply=ActionModel(
            weights=(0.1, -0.2, 0.3, 0.0, 0.4),
            bias=-1.0,
            n_pos=5,
            n_neg=15,
            roc_auc=0.7,
            log_loss=0.5,
        )
    )
    path = tmp_path / "scoring_model.json"

    model.save(path)
    loaded = ScoringModel.load(path)

    assert loaded == model


def test_load_rejects_feature_name_mismatch(tmp_path: Path) -> None:
    model = _model()
    data = model.to_dict()
    data["feature_names"] = ["recency", *FEATURE_NAMES[1:]]  # reordered -> parity violation
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError, match="feature_names"):
        ScoringModel.load(path)
