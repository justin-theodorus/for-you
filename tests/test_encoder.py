"""Unit tests for the encoder layer — no DB, no torch, no model download.

The real ``SentenceTransformerEncoder`` is covered by stubbing the lazily-imported
``sentence_transformers`` module, so these run fast and offline.
"""

from __future__ import annotations

import math
import sys
import types

import pytest

from foryou.config import EMBEDDING_DIM
from foryou.embeddings.encoder import Encoder, SentenceTransformerEncoder


class FakeEncoder:
    """Deterministic in-memory encoder used across the test suite.

    ``salt`` shifts the produced vectors so two encoders (e.g. different model
    versions) yield distinguishable embeddings for the same text.
    """

    def __init__(self, model_version: str = "fake-test-model", salt: int = 0) -> None:
        self._model_version = model_version
        self._salt = salt

    @property
    def model_version(self) -> str:
        return self._model_version

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [_unit_vector(len(text) + self._salt) for text in texts]


def _unit_vector(bump_index: int) -> list[float]:
    vec = [0.1] * EMBEDDING_DIM
    vec[bump_index % EMBEDDING_DIM] = 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def test_fake_encoder_satisfies_encoder_protocol() -> None:
    assert isinstance(FakeEncoder(), Encoder)


def test_encode_returns_one_vector_per_text_at_expected_width() -> None:
    vectors = FakeEncoder().encode(["a", "bb", "ccc"])

    assert len(vectors) == 3
    assert all(len(vector) == EMBEDDING_DIM for vector in vectors)


# --- SentenceTransformerEncoder via a stubbed sentence_transformers module ---


class _StubArray:
    def __init__(self, rows: list[list[float]]) -> None:
        self._rows = rows

    def tolist(self) -> list[list[float]]:
        return self._rows


class _StubModel:
    load_count = 0
    last_kwargs: dict[str, object] = {}

    def __init__(self, name: str) -> None:
        self.name = name
        _StubModel.load_count += 1

    def encode(self, texts: list[str], **kwargs: object) -> _StubArray:
        _StubModel.last_kwargs = kwargs
        return _StubArray([[0.0] * EMBEDDING_DIM for _ in texts])


def _install_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    _StubModel.load_count = 0
    module = types.ModuleType("sentence_transformers")
    monkeypatch.setattr(module, "SentenceTransformer", _StubModel, raising=False)
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def test_model_is_loaded_lazily_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch)
    encoder = SentenceTransformerEncoder("stub-model")

    assert _StubModel.load_count == 0  # construction does not touch the model

    encoder.encode(["hello"])
    assert _StubModel.load_count == 1  # loaded on first encode

    encoder.encode(["again"])
    assert _StubModel.load_count == 1  # reused, not reloaded


def test_encode_requests_normalized_vectors_and_exposes_model_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub(monkeypatch)
    encoder = SentenceTransformerEncoder("stub-model")

    vectors = encoder.encode(["a", "b"])

    assert _StubModel.last_kwargs["normalize_embeddings"] is True
    assert len(vectors) == 2
    assert all(len(vector) == EMBEDDING_DIM for vector in vectors)
    assert encoder.model_version == "stub-model"
