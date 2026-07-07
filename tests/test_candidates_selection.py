"""Unit tests for the selectors and Candidate immutability — pure, no DB."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from foryou.candidates.hydrator import cosine_similarity
from foryou.candidates.selection import MMRSelector, TopKSelector
from foryou.candidates.types import Candidate, SourceName, SourceTag
from tests.candidate_factories import make_context


def _scored(score: float) -> Candidate:
    return Candidate(
        post_id=uuid.uuid4(),
        sources=(SourceTag(SourceName.TRENDING, 1.0),),
        score=score,
    )


def _emb_candidate(score: float, embedding: tuple[float, ...] | None) -> Candidate:
    return Candidate(
        post_id=uuid.uuid4(),
        sources=(SourceTag(SourceName.TRENDING, 1.0),),
        score=score,
        embedding=embedding,
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


# --- MMRSelector (plan.md §5) ---

# A canonical trio: A is the top pick, B is a near-duplicate of A (cosine ~ 1), C is
# orthogonal to A (cosine 0). Diversification should promote C over B despite C's lower score.
_A = _emb_candidate(1.0, (1.0, 0.0))
_B = _emb_candidate(0.9, (0.999, 0.044))
_C = _emb_candidate(0.8, (0.0, 1.0))


def test_lambda_one_reproduces_topk_order_and_ranks() -> None:
    selector = MMRSelector(lambda_relevance=1.0)
    candidates = [_B, _C, _A]  # deliberately unsorted
    ctx = make_context(uuid.uuid4(), limit=10)

    mmr_selected = selector.select(candidates, ctx)
    topk_selected = TopKSelector().select(candidates, ctx)

    assert [c.post_id for c in mmr_selected] == [c.post_id for c in topk_selected]
    assert [c.rank for c in mmr_selected] == [0, 1, 2]


def test_promotes_dissimilar_candidate_over_near_duplicate() -> None:
    selector = MMRSelector(lambda_relevance=0.5)
    selected = selector.select([_A, _B, _C], make_context(uuid.uuid4(), limit=2))

    assert [c.post_id for c in selected] == [_A.post_id, _C.post_id]


def test_mmr_penalty_records_diversity_cost() -> None:
    selector = MMRSelector(lambda_relevance=0.5)
    selected = selector.select([_A, _B, _C], make_context(uuid.uuid4(), limit=3))
    by_id = {c.post_id: c for c in selected}

    assert selected[0].mmr_penalty == 0.0  # first pick is never penalized
    assert by_id[_C.post_id].mmr_penalty == 0.0  # orthogonal to A
    expected = (1.0 - 0.5) * cosine_similarity(_B.embedding, _A.embedding)
    assert by_id[_B.post_id].mmr_penalty == pytest.approx(expected)


def test_mmr_truncates_to_the_requested_limit() -> None:
    candidates = [_emb_candidate(float(i), (float(i), 1.0)) for i in range(10)]

    selected = MMRSelector().select(candidates, make_context(uuid.uuid4(), limit=3))

    assert len(selected) == 3
    assert [c.rank for c in selected] == [0, 1, 2]


def test_empty_input_returns_empty() -> None:
    assert MMRSelector().select([], make_context(uuid.uuid4(), limit=5)) == []


def test_all_equal_scores_run_without_divide_by_zero() -> None:
    candidates = [_emb_candidate(0.5, e) for e in ((1.0, 0.0), (0.0, 1.0), (0.7, 0.7))]

    selected = MMRSelector(lambda_relevance=0.7).select(
        candidates, make_context(uuid.uuid4(), limit=3)
    )

    assert len(selected) == 3


def test_missing_embedding_is_never_penalized() -> None:
    no_embedding = _emb_candidate(0.85, None)
    selected = MMRSelector(lambda_relevance=0.5).select(
        [_A, _B, no_embedding], make_context(uuid.uuid4(), limit=3)
    )
    by_id = {c.post_id: c for c in selected}

    assert by_id[no_embedding.post_id].mmr_penalty == 0.0


def test_per_request_lambda_overrides_constructor_default() -> None:
    # Selector built with the diversifying default, context forces pure relevance.
    selector = MMRSelector(lambda_relevance=0.5)
    ctx = make_context(uuid.uuid4(), limit=3, mmr_lambda=1.0)

    selected = selector.select([_A, _B, _C], ctx)

    assert [c.post_id for c in selected] == [_A.post_id, _B.post_id, _C.post_id]
