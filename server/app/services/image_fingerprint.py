"""Image fingerprint gate for the semantic cache.

A cached entry that carries an image is served to an image request only if BOTH
fingerprints agree (see gate()):
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

from app.config import CACHE_IMAGE_MAX_DISTANCE, CACHE_IMAGE_MAX_HAMMING

logger = logging.getLogger("dejaq.services.image_fingerprint")

_clip: SentenceTransformer | None = None


def _get_clip() -> SentenceTransformer:
    global _clip
    if _clip is None:
        logger.info("Loading clip-ViT-B-32 image embedder...")
        _clip = SentenceTransformer("clip-ViT-B-32")
    return _clip


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


def fingerprint(image_bytes: bytes) -> ImageFingerprint:
    """Compute both fingerprints for one image. Raises on undecodable bytes."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
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


def gate(
    new: ImageFingerprint,
    cached_dhash_hex: str | None,
    cached_clip_b64: str | None,
) -> bool:
    """True iff the new image matches the cached one closely enough to serve."""
    return gate_result(new, cached_dhash_hex, cached_clip_b64).passed


def _self_test() -> None:
    # dHash + hamming basics (mirror the harness self-test).
    grad = Image.new("L", (64, 64))
    for x in range(64):
        for y in range(64):
            grad.putpixel((x, y), x * 4)
    grad_rgb = grad.convert("RGB")
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
            inv.putpixel((x, y), 255 - x * 4)
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
