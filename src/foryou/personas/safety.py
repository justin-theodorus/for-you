"""Lightweight, rule-based content safety / spam gate — no LLM (plan.md §6).

Runs cheap deterministic checks before a generated post is inserted. Guardrails live
here in code, so a persona can never post its way past them regardless of prompt. The
banned-term set is illustrative (harassment / self-harm / incitement), not exhaustive —
a real system would layer a trained classifier on top.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BANNED_TERMS: frozenset[str] = frozenset(
    {
        "kill yourself",
        "kys",
        "go die",
        "you should die",
        "i will kill",
        "gas them",
        "lynch",
        "kill them all",
    }
)

_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-zA-Z']+")

_MAX_URLS = 1
_MIN_CHARS = 10
_MAX_CHARS = 500
_MAX_CAPS_RATIO = 0.7
_MIN_UNIQUE_WORD_RATIO = 0.4
_REPETITION_MIN_WORDS = 6


@dataclass(frozen=True)
class SafetyVerdict:
    """Outcome of the gate. ``category`` names the first failed check."""

    ok: bool
    reason: str | None = None
    category: str | None = None


def is_safe(content: str, *, seen: set[str] | None = None) -> SafetyVerdict:
    """Return the first violation found, or an ``ok`` verdict.

    ``seen`` (if given) rejects content already accepted this batch as a duplicate.
    """
    text = content.strip()
    lowered = text.lower()

    if len(text) < _MIN_CHARS or len(text) > _MAX_CHARS:
        return SafetyVerdict(False, "content length out of bounds", "length")

    for term in _BANNED_TERMS:
        if term in lowered:
            return SafetyVerdict(False, f"banned term: {term!r}", "banned_term")

    if len(_URL_RE.findall(text)) > _MAX_URLS:
        return SafetyVerdict(False, "too many links", "spam_url")

    letters = [c for c in text if c.isalpha()]
    if letters:
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if caps_ratio > _MAX_CAPS_RATIO:
            return SafetyVerdict(False, "excessive capitalization", "caps")

    words = _WORD_RE.findall(lowered)
    if len(words) >= _REPETITION_MIN_WORDS:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < _MIN_UNIQUE_WORD_RATIO:
            return SafetyVerdict(False, "repetitive content", "repetition")

    if seen is not None and text in seen:
        return SafetyVerdict(False, "duplicate content", "dup")

    return SafetyVerdict(True)
