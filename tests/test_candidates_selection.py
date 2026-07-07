"""Unit tests for the stub selector and Candidate immutability — pure, no DB."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from foryou.candidates.selection import TopKSelector
from foryou.candidates.types import Candidate, SourceName, SourceTag
from tests.candidate_factories import make_context


def _scored(score: float) -> Candidate:
    return Candidate(
        post_id=uuid.uuid4(),
        sources=(SourceTag(SourceName.TRENDING, 1.0),),
        score=score,
    )


def test_orders_by_descending_score_and_assigns_contiguous_ranks() -> None:
    selector = TopKSelector()
    candidates = [_scored(0.1), _scored(0.9), _scored(0.5)]

    selected = selector.select(candidates, make_context(uuid.uuid4(), limit=10))

    assert [c.score for c in selected] == [0.9, 0.5, 0.1]
    assert [c.rank for c in selected] == [0, 1, 2]


def test_truncates_to_the_requested_limit() -> None:
    selector = TopKSelector()
    candidates = [_scored(float(i)) for i in range(10)]

    selected = selector.select(candidates, make_context(uuid.uuid4(), limit=3))

    assert len(selected) == 3
    assert [c.score for c in selected] == [9.0, 8.0, 7.0]


def test_candidate_is_frozen() -> None:
    candidate = _scored(0.5)

    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.rank = 1  # type: ignore[misc]
