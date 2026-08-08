"""Shared CLIP embedder for the image-similarity test harness.

Mirrors the embedding approach the production fingerprint-gate feature would use
(SentenceTransformer CLIP model, normalized embeddings -> cosine distance = 1 - dot).
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("clip-ViT-B-32")
    return _model


def embed_images(images: list[Image.Image]) -> np.ndarray:
    """Embed a batch of PIL images, L2-normalized (cosine distance = 1 - dot)."""
    return _get_model().encode(
        images, normalize_embeddings=True, convert_to_numpy=True,
        show_progress_bar=len(images) > 50,
    )


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - np.dot(a, b))
