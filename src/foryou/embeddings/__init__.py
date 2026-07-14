"""Embedding generation: encode post content into pgvector rows."""

from __future__ import annotations

from foryou.embeddings.encoder import Encoder, SentenceTransformerEncoder
from foryou.embeddings.generator import generate_embeddings, upsert_embeddings
from foryou.embeddings.topic_centroids import generate_topic_centroids

__all__ = [
    "Encoder",
    "SentenceTransformerEncoder",
    "generate_embeddings",
    "generate_topic_centroids",
    "upsert_embeddings",
]
