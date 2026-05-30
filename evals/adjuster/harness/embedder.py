"""Embedding wrapper matching the production ChromaDB embedder.

Uses BAAI/bge-small-en-v1.5 (same as v22 normalizer and production ChromaDB config)
for consistent distance measurements.
"""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class Embedder:
    def __init__(self, model_path: str | None = None) -> None:
        self._model = SentenceTransformer(model_path or _DEFAULT_MODEL)

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
    """Cosine distance between two L2-normalized vectors: 1 - dot(a, b)."""
    return float(1.0 - np.dot(a, b))
