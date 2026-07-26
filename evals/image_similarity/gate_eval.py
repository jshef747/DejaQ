"""Validate the PRODUCTION image gate rule directly, A/B with and without the
border trim, and with/without the structural tier.

Unlike phash_gate.py (which studied a CLIP band for the old band-tier design),
this evaluates exactly what ships: app.services.image_fingerprint.gate_result().

Reports, per configuration:
  - same-group acceptance (should the same photo be served? yes) broken out by
    variant, so the pad/logo re-framing cases are visible on their own
  - cross-group FALSE ACCEPTS (different photos wrongly served) — the safety
    number that must not degrade

Run from server/:
    uv run python ../evals/image_similarity/gate_eval.py ../evals/image_similarity/dataset
"""
from __future__ import annotations

import argparse
import itertools
import sys
from collections import defaultdict
from pathlib import Path

# This directory contains an app.py (the two-photo comparer) which would shadow
# the server's `app` package; put the server root (cwd) first.
sys.path.insert(0, str(Path.cwd()))

import numpy as np
from PIL import Image

from app.config import CACHE_IMAGE_MAX_DISTANCE, CACHE_IMAGE_MAX_HAMMING
from app.services.image_fingerprint import _get_clip, dhash, hamming, trim_border

# Rejected variant, kept here so the experiment stays reproducible: accepting on
# strong dHash agreement alone with a looser CLIP ceiling. See the report below.
STRUCTURAL_HAMMING = 10
STRUCTURAL_CLIP_CEILING = 0.25

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def group_of(path: Path, sep: str = "__") -> str:
    return path.stem.split(sep, 1)[0]


def variant_of(path: Path, sep: str = "__") -> str:
    stem = path.stem
    return stem.split(sep, 1)[1] if sep in stem else "original"


def fingerprint_all(paths: list[Path], trim: bool) -> tuple[np.ndarray, list[int]]:
    """Mirror production fingerprint() over a whole folder (trim optional for A/B)."""
    images = []
    for p in paths:
        img = Image.open(p).convert("RGB")
        if trim:
            img = trim_border(img)
        images.append(img)

    hashes = [dhash(img) for img in images]
    # Bound memory before CLIP (which resizes to 224 internally anyway).
    for img in images:
        img.thumbnail((256, 256))
    vecs = _get_clip().encode(
        images, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=True
    )
    return vecs, hashes


def evaluate(
    paths: list[Path],
    vecs: np.ndarray,
    hashes: list[int],
    *,
    structural: bool,
) -> dict:
    """Apply the production gate rule to every pair; return accept statistics."""
    n = len(paths)
    groups = [group_of(p) for p in paths]
    variants = [variant_of(p) for p in paths]

    def accepts(i: int, j: int) -> bool:
        ham = hamming(hashes[i], hashes[j])
        dist = float(1.0 - np.dot(vecs[i], vecs[j]))
        if ham <= CACHE_IMAGE_MAX_HAMMING and dist <= CACHE_IMAGE_MAX_DISTANCE:
            return True
        if structural and ham <= STRUCTURAL_HAMMING and dist <= STRUCTURAL_CLIP_CEILING:
            return True
        return False

    by_variant: dict[str, list[bool]] = defaultdict(list)
    same_total = same_accept = 0
    cross_total = cross_accept = 0
    false_accepts: list[tuple[str, str, int, float]] = []

    for i, j in itertools.combinations(range(n), 2):
        ok = accepts(i, j)
        if groups[i] == groups[j]:
            same_total += 1
            same_accept += ok
            # Credit the pair to the non-original variant so "pad"/"logo" are visible.
            key = variants[j] if variants[i] == "original" else (
                variants[i] if variants[j] == "original" else f"{min(variants[i], variants[j])}+{max(variants[i], variants[j])}"
            )
            by_variant[key].append(ok)
        else:
            cross_total += 1
            if ok:
                cross_accept += 1
                ham = hamming(hashes[i], hashes[j])
                dist = float(1.0 - np.dot(vecs[i], vecs[j]))
                false_accepts.append((paths[i].name, paths[j].name, ham, dist))

    return {
        "same_total": same_total,
        "same_accept": same_accept,
        "cross_total": cross_total,
        "cross_accept": cross_accept,
        "by_variant": by_variant,
        "false_accepts": false_accepts,
    }


def print_report(label: str, res: dict) -> None:
    sa = res["same_accept"] / res["same_total"] if res["same_total"] else 0.0
    fa = res["cross_accept"] / res["cross_total"] if res["cross_total"] else 0.0
    print(f"\n=== {label} ===")
    print(f"  same-group accepted : {res['same_accept']:5d}/{res['same_total']:<6d} ({sa:.1%})")
    print(f"  cross-group FALSE ACCEPTS: {res['cross_accept']:d}/{res['cross_total']:d} ({fa:.4%})")
    print("  by variant (vs original):")
    for variant, results in sorted(res["by_variant"].items()):
        if "+" in variant:
            continue  # variant-vs-variant pairs; the vs-original rows are the readable ones
        print(f"    {variant:14s} {sum(results):3d}/{len(results):<3d} ({sum(results)/len(results):.1%})")
    for a, b, ham, dist in res["false_accepts"][:10]:
        print(f"    FALSE ACCEPT: {a} vs {b} (hamming={ham}, clip={dist:.4f})")


def main(input_dir: Path) -> None:
    paths = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not paths:
        raise SystemExit(f"No images in {input_dir}")
    print(f"{len(paths)} images, {len(set(group_of(p) for p in paths))} groups")
    print(
        f"thresholds: clip<={CACHE_IMAGE_MAX_DISTANCE} hamming<={CACHE_IMAGE_MAX_HAMMING} | "
        f"rejected structural variant: hamming<={STRUCTURAL_HAMMING} clip<={STRUCTURAL_CLIP_CEILING}"
    )

    print("\nFingerprinting WITHOUT trim...")
    vecs_raw, hashes_raw = fingerprint_all(paths, trim=False)
    print("Fingerprinting WITH trim...")
    vecs_trim, hashes_trim = fingerprint_all(paths, trim=True)

    print_report("BASELINE (no trim, no structural tier) — what shipped", evaluate(paths, vecs_raw, hashes_raw, structural=False))
    print_report("TRIM only", evaluate(paths, vecs_trim, hashes_trim, structural=False))
    print_report("TRIM + STRUCTURAL TIER — the proposed change", evaluate(paths, vecs_trim, hashes_trim, structural=True))
    print_report("STRUCTURAL TIER only (no trim)", evaluate(paths, vecs_raw, hashes_raw, structural=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    args = parser.parse_args()
    main(args.input_dir)
