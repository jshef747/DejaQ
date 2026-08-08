"""Pixel fingerprint gate — the PHOTO half of the image cache.

Text-bearing images (document screenshots, photos of a screen) are routed to
image_text.py and compared by their words instead; pixel similarity is actively
wrong for those. This module handles everything else.

A cached photo is served to a photo request only if BOTH fingerprints agree
(see gate()):
  - CLIP cosine distance: semantic similarity (catches "totally different image").
  - dHash hamming distance: pixel-structure similarity (catches "similar scene,
    different photo" — two skylines land far apart in dHash even when CLIP thinks
    they're close).

Validated offline across two datasets (own photos + INRIA Copydays); see
evals/image_similarity/. dHash is Pillow-only (ported from phash.py); CLIP is an
in-process SentenceTransformer, mirroring the BGE cache embedder in
memory_chromaDB.py. Both fingerprints are stored as scalar strings in Chroma
metadata (hex + base64) — raw image bytes are never persisted.

# ponytail: dHash is gradient-based, not rotation-invariant by design. A rotated
# re-upload fails the gate and becomes a cache miss (which just regenerates) —
# acceptable; add multi-rotation hashing only if rotated re-asks prove common.
"""
from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image
from sentence_transformers import SentenceTransformer

from app.config import (
    CACHE_IMAGE_MAX_DISTANCE,
    CACHE_IMAGE_MAX_HAMMING,
    CACHE_IMAGE_MIN_TILE_VARIETY,
)

logger = logging.getLogger("dejaq.services.image_fingerprint")

_clip: SentenceTransformer | None = None


def _get_clip() -> SentenceTransformer:
    global _clip
    if _clip is None:
        logger.info("Loading clip-ViT-B-32 image embedder...")
        _clip = SentenceTransformer("clip-ViT-B-32")
    return _clip


# Rejected: trimming blank borders before fingerprinting, to make a re-framed
# screenshot hash the same. Measured on 480 labeled images, its entire benefit
# was a synthetic "padded" variant added to the eval set (15% -> 98.3%); across
# realistic variants it was neutral-to-harmful (logo 100% -> 98.3%, overall
# 96.1% -> 95.8%). Real re-framed documents are handled by the OCR path in
# image_text.py instead, so nothing here needs to normalize framing.


def dhash(img: Image.Image, hash_size: int = 8) -> int:
    """64-bit difference hash: grayscale, resize to (hash_size+1, hash_size),
    1 bit per pixel for brighter-than-right-neighbor."""
    small = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(small.getdata())
    bits = 0
    for row in range(hash_size):
        offset = row * (hash_size + 1)
        for col in range(hash_size):
            bits <<= 1
            if pixels[offset + col] > pixels[offset + col + 1]:
                bits |= 1
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def tile_variety(img: Image.Image, grid: int = 4) -> int:
    """How many of the grid's tiles hash differently — an information-content floor.

    A near-blank page is a white rectangle, and CLIP and dHash see every white
    rectangle as the same image; measured, that produced 1,712 false merges.
    Real photos score 13-16 of 16 here while those blank renders scored under 10,
    so the two populations do not overlap and the floor is free of cost.
    """
    grey = img.convert("L")
    w, h = grey.size
    return len({
        dhash(grey.crop((gx * w // grid, gy * h // grid,
                         (gx + 1) * w // grid, (gy + 1) * h // grid)))
        for gy in range(grid) for gx in range(grid)
    })


@dataclass(frozen=True)
class ImageFingerprint:
    dhash_hex: str  # hex of the 64-bit dHash
    clip_b64: str   # base64 of the L2-normalized float32 CLIP vector


@dataclass(frozen=True)
class GateResult:
    passed: bool
    # Measured distances to the compared cached image. Both are None only when
    # there is no cached image to compare against (reason="no_cached_image");
    # otherwise both are populated even on a failing gate, for logging.
    clip_distance: float | None
    hamming: int | None
    reason: str  # "pass" | "no_cached_image" | "hamming_exceeded" | "clip_exceeded"


def fingerprint(image_bytes: bytes) -> ImageFingerprint | None:
    """Compute both fingerprints for one image. Raises on undecodable bytes.

    Returns None when the image carries too little structure to be identified by
    pixels (see tile_variety) — the caller must then neither serve nor store it.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if tile_variety(img) < CACHE_IMAGE_MIN_TILE_VARIETY:
        logger.info("image too uniform to fingerprint; not cacheable by pixels")
        return None
    vec = _get_clip().encode(img, normalize_embeddings=True, convert_to_numpy=True)
    return ImageFingerprint(
        dhash_hex=format(dhash(img), "016x"),
        clip_b64=base64.b64encode(vec.astype(np.float32).tobytes()).decode("ascii"),
    )


def _clip_distance(a_b64: str, b_b64: str) -> float:
    a = np.frombuffer(base64.b64decode(a_b64), dtype=np.float32)
    b = np.frombuffer(base64.b64decode(b_b64), dtype=np.float32)
    return float(1.0 - np.dot(a, b))


def gate_result(
    new: ImageFingerprint,
    cached_dhash_hex: str | None,
    cached_clip_b64: str | None,
) -> GateResult:
    """Evaluate the gate and report the measured distances + verdict reason.

    Both thresholds must pass to serve. A cached entry with missing image
    metadata (a text-only entry) never matches an image request. Both distances
    are computed even on a failing gate (the extra dot product is negligible)
    so callers can log the numbers regardless of which threshold tripped.
    """
    if not cached_dhash_hex or not cached_clip_b64:
        return GateResult(False, None, None, "no_cached_image")
    ham = hamming(int(new.dhash_hex, 16), int(cached_dhash_hex, 16))
    dist = _clip_distance(new.clip_b64, cached_clip_b64)
    if ham > CACHE_IMAGE_MAX_HAMMING:
        return GateResult(False, dist, ham, "hamming_exceeded")
    if dist > CACHE_IMAGE_MAX_DISTANCE:
        return GateResult(False, dist, ham, "clip_exceeded")
    return GateResult(True, dist, ham, "pass")

# Rejected: a "structural tier" that accepted strong dHash agreement (hamming
# <= 10) with a relaxed CLIP ceiling, meant to rescue document screenshots.
# Measured on all 113,280 cross-group pairs of a 480-image set it produced 39
# false accepts (vs 0 for trim alone) while adding only +0.9pp same-group
# recall. Cause: dHash degenerates on low-structure images — two unrelated 4K
# photos with a simple left-right brightness split both hash to a repeating
# 0f0f... pattern and land at hamming 8. dHash agreement alone is not evidence
# of sameness, so CLIP must keep its veto.


def gate(
    new: ImageFingerprint,
    cached_dhash_hex: str | None,
    cached_clip_b64: str | None,
) -> bool:
    """True iff the new image matches the cached one closely enough to serve."""
    return gate_result(new, cached_dhash_hex, cached_clip_b64).passed


def _self_test() -> None:
    import math

    # A smooth 2D pattern, not a plain gradient: a linear ramp hashes identically
    # in every tile, so tile_variety() correctly refuses to fingerprint it.
    grad = Image.new("L", (64, 64))
    for x in range(64):
        for y in range(64):
            grad.putpixel((x, y), int(127 + 120 * math.sin(x / 5.0) * math.cos(y / 7.0)))
    grad_rgb = grad.convert("RGB")
    assert tile_variety(grad_rgb) >= CACHE_IMAGE_MIN_TILE_VARIETY, "fixture must be varied enough"

    flat = Image.new("RGB", (64, 64), (250, 250, 250))
    assert tile_variety(flat) < CACHE_IMAGE_MIN_TILE_VARIETY, "a blank page must be refused"
    buf = io.BytesIO()
    flat.save(buf, format="PNG")
    assert fingerprint(buf.getvalue()) is None, "a blank page is not fingerprintable"
    assert dhash(grad_rgb) == dhash(grad_rgb), "dhash must be deterministic"
    assert hamming(0b1010, 0b0010) == 1
    assert hamming(0, 0) == 0

    def png(img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    a = png(grad_rgb)
    # Recompressed-as-JPEG copy of the same pixels must still gate ACCEPT.
    jbuf = io.BytesIO()
    grad_rgb.convert("RGB").save(jbuf, format="JPEG", quality=30)
    fp_a = fingerprint(a)
    fp_a2 = fingerprint(jbuf.getvalue())
    res_same = gate_result(fp_a2, fp_a.dhash_hex, fp_a.clip_b64)
    assert res_same.passed and res_same.reason == "pass", "same image (recompressed) must pass"
    assert res_same.clip_distance is not None and res_same.hamming is not None

    # A structurally inverted image must gate REJECT with populated metrics.
    inv = Image.new("L", (64, 64))
    for x in range(64):
        for y in range(64):
            inv.putpixel((x, y), 255 - grad.getpixel((x, y)))
    fp_inv = fingerprint(png(inv))
    res_diff = gate_result(fp_inv, fp_a.dhash_hex, fp_a.clip_b64)
    assert not res_diff.passed, "different image must fail the gate"
    assert res_diff.reason in ("hamming_exceeded", "clip_exceeded")
    assert res_diff.hamming is not None

    # Missing metadata (text-only entry) never matches; metrics are None.
    res_none = gate_result(fp_a, None, None)
    assert not res_none.passed and res_none.reason == "no_cached_image"
    assert res_none.clip_distance is None and res_none.hamming is None
    assert not gate(fp_a, None, None)  # bool wrapper still works

    print("self-test passed")


if __name__ == "__main__":
    _self_test()
