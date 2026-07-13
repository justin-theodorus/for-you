"""Unit tests for the rule-based safety / spam gate — no DB, no LLM."""

from __future__ import annotations

from foryou.personas.safety import is_safe


def test_accepts_clean_content() -> None:
    verdict = is_safe("A calm, ordinary post about shipping small things consistently.")

    assert verdict.ok
    assert verdict.category is None


def test_rejects_banned_term() -> None:
    verdict = is_safe("You should kill yourself, seriously, nobody wants you here.")

    assert not verdict.ok
    assert verdict.category == "banned_term"


def test_rejects_too_many_urls() -> None:
    verdict = is_safe("check http://a.com and http://b.com for the best deals ever now")

    assert not verdict.ok
    assert verdict.category == "spam_url"


def test_rejects_excessive_caps() -> None:
    verdict = is_safe("BUY NOW LIMITED OFFER CLICK HERE FAST DEAL WINNER PRIZE TODAY")

    assert not verdict.ok
    assert verdict.category == "caps"


def test_rejects_repetitive_content() -> None:
    verdict = is_safe("spam spam spam spam spam spam spam spam spam spam")

    assert not verdict.ok
    assert verdict.category == "repetition"


def test_rejects_too_short_content() -> None:
    verdict = is_safe("hi")

    assert not verdict.ok
    assert verdict.category == "length"


def test_rejects_in_batch_duplicate() -> None:
    text = "A perfectly reasonable and sufficiently long post about nothing at all."
    seen = {text}

    verdict = is_safe(text, seen=seen)

    assert not verdict.ok
    assert verdict.category == "dup"
