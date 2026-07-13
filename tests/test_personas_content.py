"""Unit tests for the content generator (LLM call + gate + retry) — no DB."""

from __future__ import annotations

from foryou.db.enums import Archetype
from foryou.personas.content import generate_post_text
from foryou.personas.llm import FakeLLM
from foryou.personas.profiles import PROFILES

_PROFILE = PROFILES[Archetype.FOUNDER]


def test_returns_safe_text_and_token_count() -> None:
    seen: set[str] = set()

    text, tokens = generate_post_text(
        FakeLLM(),
        _PROFILE,
        "startups",
        seed=1,
        max_tokens=100,
        temperature=0.9,
        max_regenerations=2,
        seen=seen,
    )

    assert text is not None
    assert tokens > 0
    assert text in seen  # accepted content is recorded for dedupe


def test_unsafe_output_is_dropped_after_exhausting_retries() -> None:
    seen: set[str] = set()

    text, tokens = generate_post_text(
        FakeLLM(unsafe=True),
        _PROFILE,
        "startups",
        seed=1,
        max_tokens=100,
        temperature=0.9,
        max_regenerations=1,
        seen=seen,
    )

    assert text is None
    # Tokens are counted across all attempts (initial + 1 regeneration = 2 calls).
    assert tokens > 0
    assert not seen


def test_output_is_truncated_to_the_profile_length_bound() -> None:
    seen: set[str] = set()

    text, _ = generate_post_text(
        FakeLLM(),
        _PROFILE,
        "startups",
        seed=1,
        max_tokens=100,
        temperature=0.9,
        max_regenerations=0,
        seen=seen,
    )

    assert text is not None
    assert len(text) <= _PROFILE.max_post_chars
