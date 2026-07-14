"""Generate one safe post or reply: LLM call -> length cap -> safety gate -> bounded retry.

Isolates the "call the model and make sure the output is acceptable" loop from the
orchestrators. Token cost of *every* attempt is returned so the budget accounting in
:mod:`foryou.personas.generator` (plan.md §6) and :mod:`foryou.live` (plan.md §8) stays
honest even when a post is regenerated or ultimately dropped.

Both entrypoints share :func:`_generate`; only the prompt differs, so the guardrail loop
can't drift between the batch and live content paths.
"""

from __future__ import annotations

from foryou.personas.llm import LLMClient
from foryou.personas.profiles import PersonaProfile, build_prompt, build_reply_prompt
from foryou.personas.safety import is_safe


def _truncate(text: str, max_chars: int) -> str:
    """Hard length bound enforced in code — cut at a word boundary when possible."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.strip()


def _generate(
    client: LLMClient,
    profile: PersonaProfile,
    system: str,
    user: str,
    *,
    seed: int,
    max_tokens: int,
    temperature: float,
    max_regenerations: int,
    seen: set[str],
) -> tuple[str | None, int]:
    """Run the guardrail loop for an assembled prompt.

    Returns ``(safe_text, tokens_consumed)`` or ``(None, tokens_consumed)``. Retries up to
    ``max_regenerations`` times (perturbing the seed) when the gate rejects the output;
    after that the content is dropped. ``seen`` is updated in place with each accepted
    result so the gate can reject in-batch duplicates.
    """
    tokens = 0
    for attempt in range(max_regenerations + 1):
        result = client.complete(
            system,
            user,
            seed=seed + attempt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        tokens += result.tokens_used
        text = _truncate(result.text, profile.max_post_chars)
        if is_safe(text, seen=seen).ok:
            seen.add(text)
            return text, tokens
    return None, tokens


def generate_post_text(
    client: LLMClient,
    profile: PersonaProfile,
    topic: str,
    *,
    seed: int,
    max_tokens: int,
    temperature: float,
    max_regenerations: int,
    seen: set[str],
) -> tuple[str | None, int]:
    """One safe standalone post on ``topic``; ``(text | None, tokens_consumed)``."""
    system, user = build_prompt(profile, topic)
    return _generate(
        client,
        profile,
        system,
        user,
        seed=seed,
        max_tokens=max_tokens,
        temperature=temperature,
        max_regenerations=max_regenerations,
        seen=seen,
    )


def generate_reply_text(
    client: LLMClient,
    profile: PersonaProfile,
    topic: str,
    parent_content: str,
    *,
    seed: int,
    max_tokens: int,
    temperature: float,
    max_regenerations: int,
    seen: set[str],
) -> tuple[str | None, int]:
    """One safe reply to ``parent_content`` (plan.md §8); ``(text | None, tokens_consumed)``."""
    system, user = build_reply_prompt(profile, topic, parent_content)
    return _generate(
        client,
        profile,
        system,
        user,
        seed=seed,
        max_tokens=max_tokens,
        temperature=temperature,
        max_regenerations=max_regenerations,
        seen=seen,
    )
