"""Sweep the document path's one threshold over every pair of a corpus.

The shipped rule serves a document when token overlap >= 0.80, a number chosen
because no different-document pair in rounds 1 and 2 ever reached it. This runs
the same sweep over any corpus, so a new population can say whether that
still holds.

    uv run python ../evals/image_similarity/doc_sweep.py feat_receipts.jsonl
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app.config import CACHE_IMAGE_TEXT_MIN_JACCARD, CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS  # noqa: E402
from gate_report import load  # noqa: E402

GRID = (0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.99)


def main(path: Path) -> None:
    recs = [r for r in load(path) if r["kind"] == "document"]
    scored = []
    for a, b in combinations(recs, 2):
        x, y = a["token_set"], b["token_set"]
        shared = len(x & y)
        if shared < CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS:
            continue
        scored.append((shared / len(x | y), a["group"] == b["group"], a["path"], b["path"]))

    n_same = sum(1 for _, s, _, _ in scored if s)
    print(f"{len(recs)} document-routed images, {n_same} same-content pairs above the "
          f"{CACHE_IMAGE_TEXT_MIN_SHARED_TOKENS}-shared-token floor, "
          f"{len(scored) - n_same} different-content")

    print(f"\n{'threshold':>10}{'recall':>9}{'merges':>9}   (shipped = "
          f"{CACHE_IMAGE_TEXT_MIN_JACCARD})")
    for t in GRID:
        served = [(j, s) for j, s, _, _ in scored if j >= t]
        hits = sum(1 for _, s in served if s)
        merges = len(served) - hits
        mark = " <-- shipped" if abs(t - CACHE_IMAGE_TEXT_MIN_JACCARD) < 1e-9 else ""
        print(f"{t:>10.2f}{100 * hits / n_same if n_same else 0:>8.1f}%{merges:>9}{mark}")

    worst = sorted((s for s in scored if not s[1]), reverse=True)[:5]
    print("\nhighest-scoring different-content pairs (the ones a threshold must clear):")
    for j, _, x, y in worst:
        print(f"  {j:.3f}  {x} <-> {y}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1
              else Path(__file__).parent / "feat_receipts.jsonl"))
