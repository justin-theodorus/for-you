"""Text -> vector encoding, isolated from the DB so it can be swapped or faked.

The generator depends only on the :class:`Encoder` protocol, so tests inject a
deterministic fake and never import ``sentence_transformers``/torch.
"""

from __future__ import annotations

from typing import Protocol, cast, runtime_checkable

from foryou.config import EMBEDDING_DIM, settings


@runtime_checkable
class Encoder(Protocol):
    """Turns text into fixed-width unit vectors and names the model that produced them."""

    @property
    def model_version(self) -> str:
        """Provenance tag stored on every ``post_embeddings`` row."""
        ...

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts into ``EMBEDDING_DIM``-wide vectors, one per text."""
        ...


class SentenceTransformerEncoder:
    """Local ``all-MiniLM-L6-v2`` encoder — 384-dim, cosine-normalized, zero API cost.

    The model (and torch) are imported lazily on first ``encode`` so importing this
    module stays cheap and unit tests can run without the heavy dependency.
    """

    def __init__(self, model_name: str = settings.embedding_model_name) -> None:
        self._model_name = model_name
        self._model: object | None = None

    @property
    def model_version(self) -> str:
        return self._model_name

    def _ensure_model(self) -> object:
        if self._model is None:
            # Lazy import: keeps torch out of the import path until encoding happens.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        # normalize_embeddings=True -> unit vectors, matching the cosine HNSW index.
        vectors = model.encode(  # type: ignore[attr-defined]
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        result = cast("list[list[float]]", vectors.tolist())
        if result and len(result[0]) != EMBEDDING_DIM:
            raise ValueError(
                f"encoder produced {len(result[0])}-dim vectors, expected {EMBEDDING_DIM}"
            )
        return result
