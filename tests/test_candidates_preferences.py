"""Unit tests for the preference layer (plan.md §4) — pure, no DB."""

from __future__ import annotations

import math
import uuid

import pytest

from foryou.candidates.preferences import (
    NEUTRAL,
    Preferences,
    resolve_preferences,
)
from foryou.candidates.scoring import (
    TOPIC_STRENGTH,
    VELOCITY_SCALE,
    HeuristicScorer,
    collapse_score,
    preference_multiplier,
)
from foryou.candidates.types import Candidate, Features, SourceName, SourceTag
from foryou.config import settings
from tests.candidate_factories import make_context

_FEATURES = Features(
    author_affinity=1.0,
    topic_match=0.5,
    recency=0.8,
    engagement_velocity=3.0,
    embedding_similarity=0.6,
)


def _candidate(
    *,
    sources: tuple[SourceTag, ...] = (SourceTag(SourceName.IN_NETWORK, 1.0),),
    embedding: tuple[float, ...] | None = None,
) -> Candidate:
    return Candidate(
        post_id=uuid.uuid4(), sources=sources, features=_FEATURES, embedding=embedding
    )


# --- resolve_preferences -----------------------------------------------------------


def test_neutral_preferences_resolve_to_no_op_knobs() -> None:
    resolved = resolve_preferences(NEUTRAL)

    assert resolved.half_life_hours == pytest.approx(settings.recency_half_life_hours)
    assert resolved.source_weights is None
    assert resolved.velocity_bias == 0.0
    assert resolved.mmr_lambda is None


def test_recency_slider_scales_half_life_around_the_default() -> None:
    default = settings.recency_half_life_hours

    steep = resolve_preferences(Preferences(recency=1.0)).half_life_hours
    flat = resolve_preferences(Preferences(recency=0.0)).half_life_hours

    assert steep == pytest.approx(default / 2.0)  # more recency = faster decay
    assert flat == pytest.approx(default * 2.0)


def test_friends_slider_boosts_in_network_and_damps_global() -> None:
    weights = resolve_preferences(Preferences(friends_global=0.0)).source_weights

    assert weights is not None
    assert weights[SourceName.IN_NETWORK] > 1.0
    assert weights[SourceName.OUT_OF_NETWORK] < 1.0
    assert weights[SourceName.TRENDING] == weights[SourceName.OUT_OF_NETWORK]


def test_global_slider_boosts_out_of_network_and_damps_in_network() -> None:
    weights = resolve_preferences(Preferences(friends_global=1.0)).source_weights

    assert weights is not None
    assert weights[SourceName.IN_NETWORK] < 1.0
    assert weights[SourceName.OUT_OF_NETWORK] > 1.0


def test_niche_viral_slider_maps_to_signed_velocity_bias() -> None:
    assert resolve_preferences(Preferences(niche_viral=1.0)).velocity_bias == pytest.approx(1.0)
    assert resolve_preferences(Preferences(niche_viral=0.0)).velocity_bias == pytest.approx(-1.0)


def test_exploration_slider_inverts_into_mmr_lambda() -> None:
    assert resolve_preferences(Preferences(exploration=0.3)).mmr_lambda == pytest.approx(0.7)
    assert resolve_preferences(Preferences(exploration=None)).mmr_lambda is None


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_out_of_range_slider_raises(value: float) -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        Preferences(recency=value)


def test_out_of_range_topic_weight_raises() -> None:
    with pytest.raises(ValueError, match="topic_weights"):
        Preferences(topic_weights={"tech": 2.0})


# --- preference_multiplier ---------------------------------------------------------


def test_neutral_context_multiplier_is_one() -> None:
    assert preference_multiplier(_candidate(), make_context(uuid.uuid4())) == 1.0


def test_source_multiplier_takes_the_strongest_surfacing_reason() -> None:
    candidate = _candidate(
        sources=(
            SourceTag(SourceName.IN_NETWORK, 1.0),
            SourceTag(SourceName.TRENDING, 1.0),
        )
    )
    ctx = make_context(
        uuid.uuid4(),
        source_weights={SourceName.IN_NETWORK: 1.5, SourceName.TRENDING: 0.5},
    )

    assert preference_multiplier(candidate, ctx) == pytest.approx(1.5)


def test_velocity_bias_rewards_high_velocity_when_positive() -> None:
    boosted = preference_multiplier(_candidate(), make_context(uuid.uuid4(), velocity_bias=1.0))
    damped = preference_multiplier(_candidate(), make_context(uuid.uuid4(), velocity_bias=-1.0))

    expected = 1.0 + math.tanh(_FEATURES.engagement_velocity / VELOCITY_SCALE)
    assert boosted == pytest.approx(expected)
    assert damped < 1.0 < boosted


def test_topic_vector_boosts_aligned_and_penalizes_opposed() -> None:
    embedding = (1.0, 0.0, 0.0)
    aligned = preference_multiplier(
        _candidate(embedding=embedding),
        make_context(uuid.uuid4(), topic_query_vector=(2.0, 0.0, 0.0)),
    )
    opposed = preference_multiplier(
        _candidate(embedding=embedding),
        make_context(uuid.uuid4(), topic_query_vector=(-2.0, 0.0, 0.0)),
    )

    assert aligned == pytest.approx(1.0 + TOPIC_STRENGTH)
    assert opposed == pytest.approx(1.0 - TOPIC_STRENGTH)


def test_missing_embedding_skips_the_topic_term() -> None:
    ctx = make_context(uuid.uuid4(), topic_query_vector=(1.0, 0.0, 0.0))

    # embedding=None -> cosine_similarity returns 0.0 -> no topic contribution.
    assert preference_multiplier(_candidate(embedding=None), ctx) == pytest.approx(1.0)


# --- scorer integration ------------------------------------------------------------


def test_neutral_scorer_score_equals_bare_collapse() -> None:
    """Load-bearing: neutral preferences reproduce the untuned score (no retrain needed)."""
    scorer = HeuristicScorer()
    candidate = _candidate()
    ctx = make_context(candidate.post_id)

    (scored,) = scorer.score([candidate], ctx)

    assert scored.preference_multiplier == pytest.approx(1.0)
    assert scored.action_scores is not None
    assert scored.score == pytest.approx(collapse_score(scored.action_scores, ctx.weight_vector))


def test_scorer_applies_the_preference_multiplier_to_the_score() -> None:
    scorer = HeuristicScorer()
    candidate = _candidate()
    ctx = make_context(candidate.post_id, source_weights={SourceName.IN_NETWORK: 2.0})

    (scored,) = scorer.score([candidate], ctx)

    assert scored.preference_multiplier == pytest.approx(2.0)
    assert scored.action_scores is not None
    base = collapse_score(scored.action_scores, ctx.weight_vector)
    assert scored.score == pytest.approx(2.0 * base)
