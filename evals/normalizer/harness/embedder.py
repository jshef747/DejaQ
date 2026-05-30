"""Embedding wrapper that matches the ChromaDB default used in production.

Production (server/app/services/memory_chromaDB.py:22-25) creates its
collection without passing an explicit embedding_function, which means
ChromaDB falls back to its DefaultEmbeddingFunction — currently
sentence-transformers/all-MiniLM-L6-v2, 384-dim, cosine space.

We reuse the same model here so cosine distances measured in the harness
match what production ChromaDB would compute at query time.
"""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder:
    def __init__(self, model_path: str | None = None) -> None:
        self._model = SentenceTransformer(model_path or _MODEL_NAME)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return a 2D array of L2-normalized embeddings (rows = texts)."""
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        vecs = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vecs.astype(np.float32)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance between two L2-normalized vectors: 1 - dot(a, b).

    Matches ChromaDB's cosine distance (collection metadata hnsw:space=cosine).
    Vectors must be L2-normalized (Embedder.embed does this).
    """
    return float(1.0 - np.dot(a, b))


def pairwise_cosine_distance(matrix: np.ndarray) -> np.ndarray:
    """Pairwise cosine distance matrix for L2-normalized rows."""
    sims = matrix @ matrix.T
    return 1.0 - sims
