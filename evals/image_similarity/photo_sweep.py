"""Sweep the photo path's two thresholds over every pair of a corpus.

gate_report.py says what the shipped constants do. This says what every other
pair of constants would have done, so the operating point is chosen from the
curve rather than defended after the fact.

The photo gate serves only when BOTH hold:
    CLIP cosine distance <= DEJAQ_CACHE_IMAGE_MAX_DISTANCE
    dHash hamming        <= DEJAQ_CACHE_IMAGE_MAX_HAMMING

    uv run python ../evals/image_similarity/photo_sweep.py feat_photos.jsonl
"""
from __future__ import annotations

import base64
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app.config import CACHE_IMAGE_MAX_DISTANCE, CACHE_IMAGE_MAX_HAMMING  # noqa: E402
from gate_report import kind, load  # noqa: E402

CLIP_GRID = (0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.40)
HAM_GRID = (0, 4, 8, 12, 15, 20, 25, 30, 64)


def main(path: Path) -> None:
    recs = [r for r in load(path) if r.get("clip") and kind(r) == "photo"]
    vecs = np.stack([np.frombuffer(base64.b64decode(r["clip"]), dtype=np.float32)
                     for r in recs])
    dh = np.array([int(r["dhash"], 16) for r in recs], dtype=np.uint64)
    groups = np.array([hash(r["group"]) for r in recs])

    ia, ib = np.array(list(combinations(range(len(recs)), 2))).T
    dist = 1.0 - np.einsum("ij,ij->i", vecs[ia], vecs[ib])
    ham = np.array([int(x).bit_count() for x in (dh[ia] ^ dh[ib])])
    same = groups[ia] == groups[ib]

    n_same, n_diff = int(same.sum()), int((~same).sum())
    print(f"{len(recs)} photo-routed images, {n_same} same-content pairs, "
          f"{n_diff} different-content")
    print(f"same-content: clip median {np.median(dist[same]):.3f}, "
          f"hamming median {np.median(ham[same]):.0f}")
    print(f"different   : clip median {np.median(dist[~same]):.3f}, "
          f"hamming median {np.median(ham[~same]):.0f}")

    print(f"\nrecall %% (merges) — shipped point is clip<={CACHE_IMAGE_MAX_DISTANCE} "
          f"ham<={CACHE_IMAGE_MAX_HAMMING}")
    print("clip\\ham " + "".join(f"{h:>14}" for h in HAM_GRID))
    for c in CLIP_GRID:
        row = f"{c:<8}"
        for h in HAM_GRID:
            ok = (dist <= c) & (ham <= h)
            r = 100 * int((ok & same).sum()) / n_same if n_same else 0
            m = int((ok & ~same).sum())
            cell = f"{r:.1f}({m})"
            if abs(c - CACHE_IMAGE_MAX_DISTANCE) < 1e-9 and h == CACHE_IMAGE_MAX_HAMMING:
                cell = "*" + cell
            row += f"{cell:>14}"
        print(row)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1
              else Path(__file__).parent / "feat_photos.jsonl"))
