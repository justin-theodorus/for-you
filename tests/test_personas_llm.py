"""Unit tests for the LLM client seam — no DB, no openai SDK, no API calls.

The real ``OpenAIClient`` is covered by stubbing the lazily-imported ``openai``
module, exactly like ``test_encoder`` stubs ``sentence_transformers``.
"""

from __future__ import annotations

import sys
import types

import pytest

from foryou.personas.llm import FakeLLM, LLMClient, OpenAIClient


def test_fake_llm_satisfies_llm_client_protocol() -> None:
    assert isinstance(FakeLLM(), LLMClient)


def test_fake_llm_is_deterministic_for_the_same_prompt() -> None:
    llm = FakeLLM()

    first = llm.complete("sys", "user", seed=1, max_tokens=100, temperature=0.9)
    second = llm.complete("sys", "user", seed=1, max_tokens=100, temperature=0.9)

    assert first == second
    assert first.tokens_used > 0


def test_fake_llm_varies_text_with_the_prompt() -> None:
    llm = FakeLLM()

    a = llm.complete("sys", "Write a post about tech.", seed=1, max_tokens=100, temperature=0.9)
    b = llm.complete("sys", "Write a post about food.", seed=1, max_tokens=100, temperature=0.9)

    # Different prompts should (very likely) hash to different pool entries.
    assert a.text != b.text or a.tokens_used == b.tokens_used


def test_unsafe_fake_llm_emits_banned_content() -> None:
    result = FakeLLM(unsafe=True).complete(
        "sys", "user", seed=1, max_tokens=100, temperature=0.9
    )

    assert "kill yourself" in result.text.lower()


# --- OpenAIClient via a stubbed openai module ---


class _StubMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubChoice:
    def __init__(self, content: str) -> None:
        self.message = _StubMessage(content)


class _StubUsage:
    def __init__(self, total_tokens: int) -> None:
        self.total_tokens = total_tokens


class _StubResponse:
    def __init__(self, content: str, total_tokens: int) -> None:
        self.choices = [_StubChoice(content)]
        self.usage = _StubUsage(total_tokens)


class _StubCompletions:
    def create(self, **kwargs: object) -> _StubResponse:
        _StubClient.last_kwargs = kwargs
        return _StubResponse("a generated post", 42)


class _StubChat:
    def __init__(self) -> None:
        self.completions = _StubCompletions()


class _StubClient:
    load_count = 0
    last_kwargs: dict[str, object] = {}

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.chat = _StubChat()
        _StubClient.load_count += 1


def _install_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    _StubClient.load_count = 0
    module = types.ModuleType("openai")
    monkeypatch.setattr(module, "OpenAI", _StubClient, raising=False)
    monkeypatch.setitem(sys.modules, "openai", module)


def test_openai_client_loads_sdk_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch)
    client = OpenAIClient(api_key="k", model="gpt-4o-mini")

    assert _StubClient.load_count == 0  # construction does not touch the SDK
    assert client.model_version == "gpt-4o-mini"

    client.complete("sys", "user", seed=3, max_tokens=100, temperature=0.9)
    assert _StubClient.load_count == 1  # loaded on first complete

    client.complete("sys", "again", seed=4, max_tokens=100, temperature=0.9)
    assert _StubClient.load_count == 1  # reused, not reloaded


def test_openai_client_maps_response_and_forwards_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub(monkeypatch)
    client = OpenAIClient(api_key="k", model="gpt-4o-mini")

    result = client.complete("sys", "user", seed=7, max_tokens=99, temperature=0.5)

    assert result.text == "a generated post"
    assert result.tokens_used == 42
    assert _StubClient.last_kwargs["seed"] == 7
    assert _StubClient.last_kwargs["max_tokens"] == 99
    assert _StubClient.last_kwargs["temperature"] == 0.5
