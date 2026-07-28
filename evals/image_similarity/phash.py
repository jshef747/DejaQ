"""Perceptual hash (dHash) for the band-tier gate experiment.

Complementary to CLIP: CLIP measures semantic similarity (fooled by two different
photos of a similar scene, e.g. two skylines); dHash measures pixel-structure
similarity (a resize/recompress/brightness change of the SAME photo barely moves
it, but a genuinely different photo -- even of a similar scene -- lands far away).

# ponytail: dHash is gradient-based, not rotation-invariant by design. A 3-degree
# rotation shifts every row's brightness gradient, so rotated variants intentionally
# fail this gate and fall back to a cache miss -- acceptable, since a miss just
# regenerates the answer.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def dhash(img: Image.Image, hash_size: int = 8) -> int:
    """64-bit (default) difference hash: resize to (hash_size+1, hash_size)
    grayscale, then 1 bit per pixel for whether it's brighter than its
    right-hand neighbor."""
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


def dhash_file(path: Path, hash_size: int = 8) -> int:
    return dhash(Image.open(path).convert("RGB"), hash_size)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
