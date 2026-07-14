"""User-facing preference sliders and their pure mapping onto pipeline knobs (plan.md §4).

:class:`Preferences` is the normalized surface a caller tunes (the CLI's flags and the web
app's slider rail): every slider is in ``[0, 1]`` with ``0.5`` the neutral centre, and
``NEUTRAL`` (all defaults) resolves to a no-op so a neutral request reproduces the untuned
feed exactly — which is what keeps the trained scorer (plan.md §3) valid without a retrain.

``resolve_preferences`` is pure (no I/O): it maps the sliders to concrete knobs
(:class:`ResolvedPreferences`) the context threads into the stages. The topic-query
vector is *not* resolved here — it needs the ``topic_centroids`` table — so it is built
in :mod:`foryou.candidates.context` instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from foryou.candidates.types import SourceName
from foryou.config import settings

# Multiplicative spread of the friends/global source mix around 1.0. At the extremes one
# side is boosted by (1 + SOURCE_MIX_SPREAD) and the other damped by (1 - SOURCE_MIX_SPREAD).
SOURCE_MIX_SPREAD = 0.5


def _check_unit(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")


@dataclass(frozen=True, slots=True)
class Preferences:
    """Normalized slider settings for one feed request; all default to neutral (no-op)."""

    recency: float = 0.5          # 0 = flat / popularity, 1 = steep decay / recency
    friends_global: float = 0.5   # 0 = friends only, 1 = global only
    niche_viral: float = 0.5      # 0 = niche / low-velocity, 1 = viral / high-velocity
    topic_weights: Mapping[str, float] = field(default_factory=dict)  # topic -> [0,1]
    exploration: float | None = None  # -> mmr_lambda; None keeps the settings default

    def __post_init__(self) -> None:
        _check_unit("recency", self.recency)
        _check_unit("friends_global", self.friends_global)
        _check_unit("niche_viral", self.niche_viral)
        for topic, weight in self.topic_weights.items():
            _check_unit(f"topic_weights[{topic!r}]", weight)
        if self.exploration is not None:
            _check_unit("exploration", self.exploration)

    def as_dict(self) -> dict[str, object]:
        """JSON-friendly snapshot for the impression audit log."""
        return {
            "recency": self.recency,
            "friends_global": self.friends_global,
            "niche_viral": self.niche_viral,
            "topic_weights": dict(self.topic_weights),
            "exploration": self.exploration,
        }


NEUTRAL = Preferences()


@dataclass(frozen=True, slots=True)
class ResolvedPreferences:
    """Concrete pipeline knobs derived from :class:`Preferences` (no-op when neutral)."""

    half_life_hours: float
    source_weights: Mapping[SourceName, float] | None  # None = no source-mix boost
    velocity_bias: float                                # [-1, 1]; 0 = no-op
    mmr_lambda: float | None                            # None = selector's own default


def resolve_preferences(prefs: Preferences) -> ResolvedPreferences:
    """Map normalized sliders to pipeline knobs. Neutral sliders yield no-op knobs."""
    # Recency: steeper decay (shorter half-life) as the slider rises. 0.5 -> the default.
    half_life_hours = settings.recency_half_life_hours * 2.0 ** (1.0 - 2.0 * prefs.recency)

    # Friends/global: boost in-network when low, out-of-network/trending when high.
    fg = prefs.friends_global
    if fg == 0.5:
        source_weights: Mapping[SourceName, float] | None = None
    else:
        in_network = 1.0 + SOURCE_MIX_SPREAD * (1.0 - 2.0 * fg)
        global_ = 1.0 + SOURCE_MIX_SPREAD * (2.0 * fg - 1.0)
        source_weights = {
            SourceName.IN_NETWORK: in_network,
            SourceName.OUT_OF_NETWORK: global_,
            SourceName.TRENDING: global_,
        }

    velocity_bias = (prefs.niche_viral - 0.5) * 2.0

    # Higher exploration -> lower relevance weight -> harder diversification.
    mmr_lambda = None if prefs.exploration is None else 1.0 - prefs.exploration

    return ResolvedPreferences(
        half_life_hours=half_life_hours,
        source_weights=source_weights,
        velocity_bias=velocity_bias,
        mmr_lambda=mmr_lambda,
    )
