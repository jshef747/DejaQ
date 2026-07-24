"""Perceptual-hash (dHash) gate experiment for the band-tier safeguard.

Tests whether a millisecond, deterministic dHash check can replace the slow
(~4.5s/image) caption+validator safeguard for telling apart same-photo variants
(resize/recompress/brightness -- expected small hamming distance) from
different-photo pairs (expected large), on the exact same labeled pairs used
in the caption experiment (validate_pairs.py) for direct comparison.

Run from server/ (reuses its venv; no Ollama/models needed):
    uv run python ../evals/image_similarity/phash_gate.py ../evals/image_similarity/dataset
    uv run python ../evals/image_similarity/phash_gate.py --self-test
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

from cluster import load_and_embed
from phash import dhash, dhash_file, hamming
from report_he import write_phash_report
from validate_pairs import select_pairs

MAX_HAMMING_SWEEP = 20


def variant_of(path: Path, sep: str = "__") -> str:
    stem = path.stem
    return stem.split(sep, 1)[1] if sep in stem else "original"


def run(input_dir: Path, band_min: float, band_max: float, max_pairs: int, threshold_override: int | None = None) -> None:
    valid_paths, dist_matrix = load_and_embed(input_dir)
    pairs = select_pairs(valid_paths, dist_matrix, band_min, band_max, max_pairs)
    n_cross = sum(1 for p in pairs if p["expected"] == "REJECT")
    n_same = sum(1 for p in pairs if p["expected"] == "ACCEPT")
    print(f"Selected {n_cross} cross-group pairs (expect REJECT) and {n_same} same-group pairs (expect ACCEPT)")

    unique_indices = sorted({p["i"] for p in pairs} | {p["j"] for p in pairs})
    hashes: dict[int, int] = {}
    timings = []
    for idx in unique_indices:
        start = time.time()
        hashes[idx] = dhash_file(valid_paths[idx])
        timings.append((time.time() - start) * 1000)

    print(f"Hashed {len(unique_indices)} images, mean={np.mean(timings):.3f}ms")

    for p in pairs:
        p["hamming"] = hamming(hashes[p["i"]], hashes[p["j"]])
        p["path_i"] = valid_paths[p["i"]]
        p["path_j"] = valid_paths[p["j"]]

    cross_pairs = [p for p in pairs if p["expected"] == "REJECT"]
    same_pairs = [p for p in pairs if p["expected"] == "ACCEPT"]

    print(f"\n{'hamming<=':>10} {'cross_reject':>13} {'same_accept':>12}")
    sweep_rows = []
    for t in range(0, MAX_HAMMING_SWEEP + 1):
        cross_correct = sum(1 for p in cross_pairs if p["hamming"] > t)
        same_correct = sum(1 for p in same_pairs if p["hamming"] <= t)
        cr = cross_correct / len(cross_pairs) if cross_pairs else None
        sa = same_correct / len(same_pairs) if same_pairs else None
        sweep_rows.append({"threshold": t, "cross_reject": cr, "same_accept": sa})
        print(f"{t:>10} {cr:>13.3f} {sa:>12.3f}")

    if threshold_override is not None:
        threshold = threshold_override
        best = next(r for r in sweep_rows if r["threshold"] == threshold)
        print(
            f"\nManual threshold override: hamming <= {threshold} "
            f"(cross_reject={best['cross_reject']:.3f}, same_accept={best['same_accept']:.3f})"
        )
    else:
        # auto-pick: maximize cross-group rejection first (safety), then same-group acceptance.
        # NOTE: this is naive -- it doesn't know that most "cross-group" failures are ambiguous
        # recurring-content cases (see the caption experiment), not real danger, so it tends to
        # under-shoot. Use --threshold-override once you've inspected the sweep table yourself.
        best = max(sweep_rows, key=lambda r: (r["cross_reject"], r["same_accept"]))
        threshold = best["threshold"]
        print(
            f"\nAuto-recommended threshold: hamming <= {threshold} "
            f"(cross_reject={best['cross_reject']:.3f}, same_accept={best['same_accept']:.3f})"
        )

    for p in pairs:
        p["verdict"] = "ACCEPT" if p["hamming"] <= threshold else "REJECT"
        p["correct"] = p["verdict"] == p["expected"]

    for p in pairs:
        names = {p["path_i"].name, p["path_j"].name}
        if any("src063" in n for n in names) and any("src084" in n for n in names):
            print(f"\nHeadline pair (London/NYC): hamming={p['hamming']} verdict={p['verdict']} expected={p['expected']}")

    by_variant: dict[str, list[bool]] = defaultdict(list)
    for p in same_pairs:
        v_i, v_j = variant_of(p["path_i"]), variant_of(p["path_j"])
        key = "+".join(sorted({v_i, v_j}))
        by_variant[key].append(p["correct"])

    print("\nSame-group acceptance by variant combination:")
    for variant, results in sorted(by_variant.items()):
        print(f"  {variant:25s} {sum(results)}/{len(results)} ({sum(results) / len(results):.2f})")

    report_path = write_phash_report(
        out_path=input_dir / "phash_report.html",
        input_dir=input_dir,
        pairs=pairs,
        sweep_rows=sweep_rows,
        recommended_threshold=threshold,
        mean_hash_ms=float(np.mean(timings)),
        by_variant=by_variant,
    )
    print(f"\nHebrew pHash report: {report_path}")


def self_test() -> None:
    grad = Image.new("L", (64, 64))
    for x in range(64):
        for y in range(64):
            grad.putpixel((x, y), x * 4)
    grad_rgb = grad.convert("RGB")

    h1 = dhash(grad_rgb)
    h2 = dhash(grad_rgb)
    assert h1 == h2, "dhash must be deterministic"

    brighter = ImageEnhance.Brightness(grad_rgb).enhance(1.2)
    h_bright = dhash(brighter)
    assert hamming(h1, h_bright) <= 2, (
        f"brightness shift should barely move the hash, got hamming={hamming(h1, h_bright)}"
    )

    inv = Image.new("L", (64, 64))
    for x in range(64):
        for y in range(64):
            inv.putpixel((x, y), 255 - x * 4)
    h_inv = dhash(inv.convert("RGB"))
    assert hamming(h1, h_inv) > 20, (
        f"structurally different image should hash far away, got hamming={hamming(h1, h_inv)}"
    )

    assert hamming(0b1010, 0b0010) == 1
    assert hamming(0, 0) == 0
    print("self-test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", nargs="?", type=Path)
    parser.add_argument("--band-min", type=float, default=0.03)
    parser.add_argument("--band-max", type=float, default=0.07)
    parser.add_argument("--max-pairs", type=int, default=40)
    parser.add_argument("--threshold-override", type=int, default=None, help="manually pin the hamming threshold instead of auto-picking")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        sys.exit(0)

    if not args.input_dir:
        parser.error("input_dir is required unless --self-test is passed")

    run(args.input_dir, args.band_min, args.band_max, args.max_pairs, args.threshold_override)
