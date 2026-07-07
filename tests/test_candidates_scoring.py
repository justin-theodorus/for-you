"""Unit tests for the scorers — pure, no DB."""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path

import pytest

from foryou.candidates.scoring import HeuristicScorer, TrainedScorer, collapse_score
from foryou.candidates.types import (
    ACTION_KEYS,
    ActionScores,
    Candidate,
    Features,
    SourceName,
    SourceTag,
)
from foryou.scoring.model import FEATURE_NAMES, ActionModel, ScoringModel, features_to_vector
from tests.candidate_factories import make_context


def _candidate(features: Features) -> Candidate:
    return Candidate(
        post_id=uuid.uuid4(),
        sources=(SourceTag(SourceName.IN_NETWORK, 1.0),),
        features=features,
    )


_FEATURES = Features(
    author_affinity=1.0,
    topic_match=0.5,
    recency=0.8,
    engagement_velocity=2.0,
    embedding_similarity=0.6,
)


def test_score_is_weighted_sum_of_action_probabilities() -> None:
    scorer = HeuristicScorer()
    candidate = _candidate(_FEATURES)
    ctx = make_context(candidate.post_id)

    (scored,) = scorer.score([candidate], ctx)

    assert scored.action_scores is not None
    expected = sum(scored.action_scores.as_dict().values())  # uniform weights of 1.0
    assert scored.score == pytest.approx(expected)


def test_score_is_monotonic_in_author_affinity() -> None:
    scorer = HeuristicScorer()
    low = _candidate(dataclasses.replace(_FEATURES, author_affinity=0.0))
    high = _candidate(dataclasses.replace(_FEATURES, author_affinity=1.0))
    ctx = make_context(low.post_id)

    scored_low, scored_high = scorer.score([low, high], ctx)

    assert scored_high.score is not None and scored_low.score is not None
    assert scored_high.score > scored_low.score


def test_scoring_unhydrated_candidate_raises() -> None:
    scorer = HeuristicScorer()
    candidate = Candidate(
        post_id=uuid.uuid4(),
        sources=(SourceTag(SourceName.IN_NETWORK, 1.0),),
    )

    with pytest.raises(ValueError, match="hydrated"):
        scorer.score([candidate], make_context(candidate.post_id))


def test_scoring_does_not_mutate_the_input_candidate() -> None:
    scorer = HeuristicScorer()
    candidate = _candidate(_FEATURES)

    scorer.score([candidate], make_context(candidate.post_id))

    assert candidate.score is None  # input untouched; a new object carries the score
    assert candidate.action_scores is None


def test_collapse_score_is_the_weighted_sum_of_action_probabilities() -> None:
    actions = ActionScores(like=0.9, reply=0.1, repost=0.2, quote=0.3, dwell=0.4)
    weights = {"like": 2.0, "reply": 1.0, "repost": 0.0, "quote": 1.0, "dwell": 0.5}

    total = collapse_score(actions, weights)

    assert total == pytest.approx(2.0 * 0.9 + 0.1 + 0.0 + 0.3 + 0.5 * 0.4)


def test_heuristic_score_equals_collapse_of_its_action_scores() -> None:
    scorer = HeuristicScorer()
    candidate = _candidate(_FEATURES)
    ctx = make_context(candidate.post_id)

    (scored,) = scorer.score([candidate], ctx)

    assert scored.action_scores is not None
    assert scored.score == pytest.approx(collapse_score(scored.action_scores, ctx.weight_vector))


def _trained_model() -> ScoringModel:
    actions = {
        action: ActionModel(
            weights=tuple(0.1 * (index + 1) for index in range(len(FEATURE_NAMES))),
            bias=-0.5 + 0.2 * action_index,
            n_pos=10,
            n_neg=30,
            roc_auc=0.8,
            log_loss=0.4,
        )
        for action_index, action in enumerate(ACTION_KEYS)
    }
    return ScoringModel(
        actions=actions,
        feature_names=FEATURE_NAMES,
        model_version="test-v1",
        trained_at="2026-07-01T00:00:00+00:00",
    )


def _saved_scorer(tmp_path: Path) -> TrainedScorer:
    path = tmp_path / "scoring_model.json"
    _trained_model().save(path)
    return TrainedScorer(path)


def test_trained_scorer_scores_are_predict_proba_collapsed(tmp_path: Path) -> None:
    scorer = _saved_scorer(tmp_path)
    candidate = _candidate(_FEATURES)
    ctx = make_context(candidate.post_id)

    (scored,) = scorer.score([candidate], ctx)

    expected = ActionScores(**_trained_model().predict_proba(features_to_vector(_FEATURES)))
    assert scored.action_scores == expected
    assert scored.score == pytest.approx(collapse_score(expected, ctx.weight_vector))


def test_trained_scorer_is_deterministic(tmp_path: Path) -> None:
    scorer = _saved_scorer(tmp_path)
    candidate = _candidate(_FEATURES)
    ctx = make_context(candidate.post_id)

    (first,) = scorer.score([candidate], ctx)
    (second,) = scorer.score([candidate], ctx)

    assert first.score == second.score
    assert first.action_scores == second.action_scores


def test_trained_scorer_does_not_mutate_input(tmp_path: Path) -> None:
    scorer = _saved_scorer(tmp_path)
    candidate = _candidate(_FEATURES)

    scorer.score([candidate], make_context(candidate.post_id))

    assert candidate.score is None
    assert candidate.action_scores is None


def test_trained_scorer_unhydrated_candidate_raises(tmp_path: Path) -> None:
    scorer = _saved_scorer(tmp_path)
    candidate = Candidate(post_id=uuid.uuid4(), sources=(SourceTag(SourceName.IN_NETWORK, 1.0),))

    with pytest.raises(ValueError, match="hydrated"):
        scorer.score([candidate], make_context(candidate.post_id))


def test_trained_scorer_reports_model_version(tmp_path: Path) -> None:
    assert _saved_scorer(tmp_path).model_version == "test-v1"
