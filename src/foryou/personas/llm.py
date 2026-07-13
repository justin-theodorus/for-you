"""LLM client seam for persona content generation, isolated from the DB and SDK.

Mirrors ``foryou.embeddings.encoder``: the generator depends only on the
:class:`LLMClient` protocol, so tests (and no-API-key runs) use the deterministic
:class:`FakeLLM` and never import ``openai``. The real :class:`OpenAIClient` imports
the SDK lazily on first call so importing this module stays cheap.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from foryou.config import settings


@dataclass(frozen=True)
class LLMResult:
    """A single completion plus the tokens it cost (for budget accounting)."""

    text: str
    tokens_used: int


@runtime_checkable
class LLMClient(Protocol):
    """Turns a (system, user) prompt into one short post and names the model."""

    @property
    def model_version(self) -> str:
        """Provenance tag for generated content (e.g. ``gpt-4o-mini``)."""
        ...

    def complete(
        self,
        system: str,
        user: str,
        *,
        seed: int | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        """Return a single completion for the prompt."""
        ...


class OpenAIClient:
    """OpenAI chat-completions client. The SDK is imported lazily on first call."""

    def __init__(self, *, api_key: str, model: str = settings.openai_model) -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any | None = None

    @property
    def model_version(self) -> str:
        return self._model

    def _ensure_client(self) -> Any:
        if self._client is None:
            # Lazy import: keeps the openai SDK out of the import path until used.
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def complete(
        self,
        system: str,
        user: str,
        *,
        seed: int | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        client = self._ensure_client()
        response = client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return LLMResult(text=str(text), tokens_used=int(tokens))


# Deterministic content pool for the offline fake — generic, always-safe one-liners.
# The topic is carried on the prompt, so hashing (system, user, seed) already varies
# the pick per topic/persona; the post is tagged with its topic by the generator.
_FAKE_POOL: list[str] = [
    "Been thinking about this all week and the simple version keeps winning.",
    "Underrated take: the boring, consistent approach compounds faster than the clever one.",
    "Small update from today — shipped something I'm actually proud of.",
    "The more I learn here, the more I realize how much is just showing up daily.",
    "Hot take that will age well: attention to the fundamentals beats chasing the trend.",
    "Quiet reminder that most overnight successes were years of unglamorous work.",
    "Reworked my whole approach this month and the difference is night and day.",
    "If you're on the fence about starting: the second-best time is right now.",
    "The details nobody talks about are usually the ones that decide the outcome.",
    "Spent the afternoon unlearning a habit that used to feel like a strength.",
    "Convinced that taste is just the residue of a thousand small, deliberate choices.",
    "Every shortcut I skipped this year quietly paid for itself twice over.",
    "The version of this I'd have shipped a year ago would embarrass me now.",
    "Curiosity beats discipline on the days discipline runs out — keep some in reserve.",
    "Most of my best decisions looked boring from the outside and felt obvious in hindsight.",
    "Note to self: the work you resist the most is usually the work that moves the needle.",
]

# Emitted by FakeLLM(unsafe=True) to exercise the safety-gate reject path in tests.
_FAKE_UNSAFE = "kill yourself, nobody wants you here — banned content for the gate."


class FakeLLM:
    """Deterministic, offline stand-in for :class:`LLMClient`.

    Ships in ``src`` (not just tests) because OpenAI has no offline mode: the CLI
    needs a real, importable fallback when ``OPENAI_API_KEY`` is unset. Content is a
    pure function of ``(system, user, seed)`` via SHA-256 (``hash()`` is per-process
    salted and would break reproducibility).
    """

    def __init__(self, model_version: str = "fake-llm", *, unsafe: bool = False) -> None:
        self._model_version = model_version
        self._unsafe = unsafe

    @property
    def model_version(self) -> str:
        return self._model_version

    def complete(
        self,
        system: str,
        user: str,
        *,
        seed: int | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        if self._unsafe:
            return LLMResult(text=_FAKE_UNSAFE, tokens_used=max(1, len(_FAKE_UNSAFE) // 4))
        # Compose two pool sentences from independent digest halves so the offline
        # corpus has enough variety (~pool^2) to fill a real run without the batch
        # dedupe rejecting most posts; identical draws still exercise that gate.
        digest = int(hashlib.sha256(f"{system}\n{user}\n{seed}".encode()).hexdigest(), 16)
        first = _FAKE_POOL[digest % len(_FAKE_POOL)]
        second = _FAKE_POOL[(digest // len(_FAKE_POOL)) % len(_FAKE_POOL)]
        text = first if second == first else f"{first} {second}"
        return LLMResult(text=text, tokens_used=max(1, len(text) // 4))
