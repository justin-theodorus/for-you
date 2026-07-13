"""Generate one safe post: LLM call -> length cap -> safety gate -> bounded retry.

Isolates the "call the model and make sure the output is acceptable" loop from the
orchestrator. Token cost of *every* attempt is returned so the budget accounting in
:mod:`foryou.personas.generator` stays honest even when a post is regenerated.
"""

from __future__ import annotations

from foryou.personas.llm import LLMClient
from foryou.personas.profiles import PersonaProfile, build_prompt
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
    """Return ``(safe_text, tokens_consumed)`` or ``(None, tokens_consumed)``.

    Retries up to ``max_regenerations`` times (perturbing the seed) when the gate
    rejects the output; after that the post is dropped. ``seen`` is updated in place
    with each accepted post so the gate can reject in-batch duplicates.
    """
    system, user = build_prompt(profile, topic)
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
