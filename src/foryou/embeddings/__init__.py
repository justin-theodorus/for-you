"""Embedding generation: encode post content into pgvector rows."""

from __future__ import annotations

from foryou.embeddings.encoder import Encoder, SentenceTransformerEncoder
from foryou.embeddings.generator import generate_embeddings

__all__ = ["Encoder", "SentenceTransformerEncoder", "generate_embeddings"]
