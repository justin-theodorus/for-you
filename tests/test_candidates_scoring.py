"""Unit tests for the stub scorer — pure, no DB."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from foryou.candidates.scoring import HeuristicScorer
from foryou.candidates.types import Candidate, Features, SourceName, SourceTag
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
