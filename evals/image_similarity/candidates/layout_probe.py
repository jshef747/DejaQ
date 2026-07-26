"""Layout / spatial probe for the document-image cache-matching problem.

Family under test: does WHERE words sit on the page discriminate same-content
image pairs from different-content pairs, in a way that beats plain OCR
token-set Jaccard (baseline: 45.4% recall at 0 false merges)?

All approaches are scored through the shared protocol.py (unchanged) so
results are comparable across agents run on this same task.

IMPORTANT data note: the precomputed "tokens" field in features_rich.jsonl is
a *deduplicated, alphabetically-sorted* set of normalized words -- it is NOT
positionally aligned with the "words" list (word_count=138 but tokens has 101
entries, tokens[0]='2025' while words[0] is a Hebrew word). For any
position-aware method we must derive our own per-word normalized text
straight from "words" (text, confidence, x, y, w, h) and keep it aligned to
position ourselves.

Approaches implemented:
  1. spatial_inlier_count  -- match uniquely-occurring normalized words
     between two images, fit an independent per-axis (scale, translate)
     transform with iterative sigma-clipping (robust to OCR noise / a few
     wrong correspondences), score = number of geometrically-consistent
     ("inlier") matches.
  2. spatial_inlier_frac   -- same fit, score = inlier fraction (gated: below
     a minimum match count the fraction is meaningless, score falls back to 0).
  3. jaccard_gated_by_spatial -- min(token_jaccard, spatial_inlier_frac): text
     overlap AND spatial consistency both required.
  4. line_structure_score  -- group words into text lines by y, align the two
     images' ordered line sequences (bag-of-words-per-line Jaccard + an LCS-like
     order-preserving match), invariant to crop/scale because it only uses
     relative order, not absolute coordinates.
  5. tile_hamming_similarity -- sanity-check baseline using the precomputed
     4x4 per-tile dHash grid (pixel-space, fixed absolute grid); included to
     confirm/deny it survives crop+scale (expected to fail: tiles are cut on
     absolute image geometry, not content-relative).

Run:
    cd server
    uv run python ../evals/image_similarity/candidates/layout_probe.py
"""
from __future__ import annotations

import re
import sys
import time
from itertools import combinations

import numpy as np

SCRATCH = "evals/image_similarity"
sys.path.insert(0, SCRATCH)
from protocol import load, evaluate, report, token_jaccard, BASELINE_ZERO_MERGE_RECALL  # noqa: E402

# ---------------------------------------------------------------------------
# Per-word normalization (independent of the precomputed "tokens" field, since
# that field is not position-aligned).
# ---------------------------------------------------------------------------

_STRIP_CHARS = "\u200f\u200e\"'`.,:;!?()[]{}|*\u00a9\u2014-"


def normalize_word(text: str) -> str:
    t = text.strip(_STRIP_CHARS)
    t = t.lower()
    return t


def build_spatial_index(rec: dict) -> dict:
    """Precompute, once per record: all normalized (text,pos) entries, and the
    subset of texts that occur exactly once in this image (usable as
    unambiguous anchors for point correspondence)."""
    entries = []  # (text, x, y)  using box center
    counts: dict[str, int] = {}
    for w in rec["words"]:
        text, conf, x, y, ww, hh = w
        norm = normalize_word(text)
        if len(norm) < 2:
            continue
        cx, cy = x + ww / 2.0, y + hh / 2.0
        entries.append((norm, cx, cy))
        counts[norm] = counts.get(norm, 0) + 1
    anchors = {}
    for norm, cx, cy in entries:
        if counts[norm] == 1:
            anchors[norm] = (cx, cy)
    rec["_spatial_entries"] = entries
    rec["_spatial_anchors"] = anchors
    return rec


def build_lines(rec: dict) -> list:
    """Group words into text lines by y-proximity, ordered top-to-bottom, each
    line's tokens ordered left-to-right. Returns list[set[str]] (bag of
    normalized tokens per line) plus list[str] (joined line text) - used by
    line_structure_score. Crop/scale invariant: uses only relative order and
    per-line bag-of-words, never absolute coordinates."""
    words = []
    for w in rec["words"]:
        text, conf, x, y, ww, hh = w
        norm = normalize_word(text)
        if len(norm) < 2:
            continue
        words.append((y + hh / 2.0, x, norm, hh))
    if not words:
        rec["_lines"] = []
        return rec
    words.sort(key=lambda t: (t[0], t[1]))
    heights = [h for _, _, _, h in words]
    line_h = float(np.median(heights)) if heights else 0.02
    thresh = max(line_h * 0.6, 0.005)

    lines = []
    cur = [words[0]]
    for item in words[1:]:
        if item[0] - cur[-1][0] > thresh:
            lines.append(cur)
            cur = [item]
        else:
            cur.append(item)
    lines.append(cur)

    line_bags = []
    for ln in lines:
        ln_sorted = sorted(ln, key=lambda t: t[1])
        line_bags.append(frozenset(t[2] for t in ln_sorted))
    rec["_lines"] = line_bags
    return rec


# ---------------------------------------------------------------------------
# Robust per-axis (scale, translate) fit with iterative sigma-clipping.
# ---------------------------------------------------------------------------

def _fit_axis_robust(a_vals: np.ndarray, b_vals: np.ndarray, n_iter: int = 3, clip_k: float = 3.0,
                      min_tol: float = 0.01):
    """Fit b = s*a + t via least squares, iteratively dropping outliers.
    Returns (s, t, inlier_mask)."""
    mask = np.ones(len(a_vals), dtype=bool)
    s, t = 1.0, 0.0
    for _ in range(n_iter):
        if mask.sum() < 2:
            break
        av, bv = a_vals[mask], b_vals[mask]
        if np.ptp(av) < 1e-9:
            # degenerate (all same x or y) -- can't estimate scale, assume 1:1
            s = 1.0
            t = float(np.median(bv - av))
        else:
            s, t = np.polyfit(av, bv, 1)
        resid_all = b_vals - (s * a_vals + t)
        std = np.std(resid_all[mask]) if mask.sum() > 1 else min_tol
        tol = max(clip_k * std, min_tol)
        mask = np.abs(resid_all) < tol
    return s, t, mask


def spatial_fit(a: dict, b: dict, min_matches: int = 6, tol: float = 0.025):
    """Match unique-occurring normalized words between a and b, fit an
    independent per-axis affine transform (with sigma clipping), return
    (n_matches, n_inliers, inlier_fraction)."""
    anchors_a = a["_spatial_anchors"]
    anchors_b = b["_spatial_anchors"]
    common = anchors_a.keys() & anchors_b.keys()
    n = len(common)
    if n < min_matches:
        return n, 0, 0.0

    xa = np.array([anchors_a[k][0] for k in common])
    ya = np.array([anchors_a[k][1] for k in common])
    xb = np.array([anchors_b[k][0] for k in common])
    yb = np.array([anchors_b[k][1] for k in common])

    sx, tx, mask_x = _fit_axis_robust(xa, xb)
    sy, ty, mask_y = _fit_axis_robust(ya, yb)

    pred_xb = sx * xa + tx
    pred_yb = sy * ya + ty
    resid = np.sqrt((pred_xb - xb) ** 2 + (pred_yb - yb) ** 2)
    inliers = resid < tol
    return n, int(inliers.sum()), float(inliers.sum()) / n


def spatial_inlier_count(a: dict, b: dict) -> float:
    n, n_in, frac = spatial_fit(a, b)
    return float(n_in)


def spatial_inlier_frac(a: dict, b: dict) -> float:
    n, n_in, frac = spatial_fit(a, b)
    return frac


def jaccard_gated_by_spatial(a: dict, b: dict) -> float:
    jac = token_jaccard(a, b)
    n, n_in, frac = spatial_fit(a, b)
    return min(jac, frac)


def jaccard_times_spatial(a: dict, b: dict) -> float:
    jac = token_jaccard(a, b)
    n, n_in, frac = spatial_fit(a, b)
    return jac * frac


# ---------------------------------------------------------------------------
# Line structure comparison (order-preserving, crop/scale invariant).
# ---------------------------------------------------------------------------

def _line_similarity(bag_a: frozenset, bag_b: frozenset) -> float:
    u = bag_a | bag_b
    if not u:
        return 0.0
    return len(bag_a & bag_b) / len(u)


def line_structure_score(a: dict, b: dict, line_match_thresh: float = 0.4) -> float:
    la, lb = a["_lines"], b["_lines"]
    na, nb = len(la), len(lb)
    if na == 0 or nb == 0:
        return 0.0
    # DP LCS where "match" = line similarity >= line_match_thresh
    # dp[i][j] = length of best order-preserving line alignment using la[:i], lb[:j]
    dp = np.zeros((na + 1, nb + 1), dtype=np.float32)
    for i in range(1, na + 1):
        bag_i = la[i - 1]
        for j in range(1, nb + 1):
            sim = _line_similarity(bag_i, lb[j - 1])
            if sim >= line_match_thresh:
                dp[i, j] = dp[i - 1, j - 1] + 1
            else:
                dp[i, j] = max(dp[i - 1, j], dp[i, j - 1])
    lcs = dp[na, nb]
    return float(2 * lcs / (na + nb))


# ---------------------------------------------------------------------------
# Tile dHash sanity check (expected to fail under crop/scale - fixed absolute
# grid, not content-relative).
# ---------------------------------------------------------------------------

def _hamming(h1: str, h2: str) -> int:
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


def tile_hamming_similarity(a: dict, b: dict) -> float:
    ta, tb = a["tiles"], b["tiles"]
    dists = [_hamming(x, y) for x, y in zip(ta, tb) if x != "0" * 16 or y != "0" * 16]
    if not dists:
        return 0.0
    mean_dist = float(np.mean(dists))
    # convert to similarity (lower hamming = more similar); each tile hash is
    # 32 bits (8 hex chars *4)? -- values observed are 16 hex chars = 64 bits
    max_bits = 64
    return 1.0 - (mean_dist / max_bits)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    recs = load()
    print(f"{len(recs)} document images, {len({r['group'] for r in recs})} groups")

    for r in recs:
        build_spatial_index(r)
        build_lines(r)

    n_anchor_stats = [len(r["_spatial_anchors"]) for r in recs]
    print(f"anchors per image: min={min(n_anchor_stats)} median={np.median(n_anchor_stats):.0f} "
          f"max={max(n_anchor_stats)}")
    n_lines_stats = [len(r["_lines"]) for r in recs]
    print(f"lines per image: min={min(n_lines_stats)} median={np.median(n_lines_stats):.0f} "
          f"max={max(n_lines_stats)}")

    report(evaluate(recs, token_jaccard, "BASELINE token-set Jaccard"))

    approaches = [
        ("spatial_inlier_count", spatial_inlier_count),
        ("spatial_inlier_frac", spatial_inlier_frac),
        ("jaccard_gated_by_spatial (min)", jaccard_gated_by_spatial),
        ("jaccard_times_spatial (product)", jaccard_times_spatial),
        ("line_structure_score", line_structure_score),
        ("tile_hamming_similarity (sanity check)", tile_hamming_similarity),
    ]

    n_pairs = len(recs) * (len(recs) - 1) // 2
    print(f"\n{n_pairs} pairs total\n")

    for name, fn in approaches:
        t0 = time.perf_counter()
        result = evaluate(recs, fn, name)
        elapsed = time.perf_counter() - t0
        per_pair_us = (elapsed / n_pairs) * 1e6
        report(result)
        print(f"    runtime: {elapsed:.2f}s total, {per_pair_us:.1f} us/pair")

    print(f"\nBaseline to beat: {100*BASELINE_ZERO_MERGE_RECALL:.1f}% recall @ 0 false merges")


if __name__ == "__main__":
    main()
