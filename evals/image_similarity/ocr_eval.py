"""Score the production DOCUMENT gate over a labeled folder of document images.

Answers the two questions that set the thresholds:
  - do all renderings of the SAME document match (screenshots, PDF renders,
    photos of a screen)?
  - do DIFFERENT documents stay apart, especially ones sharing a template?

Ground truth comes from the filename prefix before `__`, same convention as the
photo harness: `docNNN__variant.png`. Everything is measured with the shipped
functions in app.services.image_text, so eval and production cannot drift.

Run from server/:
    uv run python ../evals/image_similarity/ocr_eval.py <folder>
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

# This directory contains an app.py (the two-photo comparer) which would shadow
# the server's `app` package; put the server root (cwd) first.
sys.path.insert(0, str(Path.cwd()))

from app.config import (
    CACHE_IMAGE_TEXT_DIGIT_MIN_JACCARD,
    CACHE_IMAGE_TEXT_MIN_JACCARD,
    CACHE_IMAGE_TEXT_NO_DIGIT_JACCARD,
)
from app.services.image_text import extract, matches

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def group_of(path: Path, sep: str = "__") -> str:
    return path.stem.split(sep, 1)[0]


def main(folder: Path) -> None:
    paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not paths:
        raise SystemExit(f"No images in {folder}")
    print(
        f"thresholds: token>={CACHE_IMAGE_TEXT_MIN_JACCARD} digit>={CACHE_IMAGE_TEXT_DIGIT_MIN_JACCARD} "
        f"(no-digit fallback {CACHE_IMAGE_TEXT_NO_DIGIT_JACCARD})"
    )

    results = {}
    for p in paths:
        t0 = time.time()
        results[p] = extract(p.read_bytes())
        ms = (time.time() - t0) * 1000
        r = results[p]
        print(f"  {p.name:34s} {'document' if r.is_document else 'photo   '} "
              f"words={r.word_count:4d} conf={r.mean_confidence:5.1f} {ms:6.0f}ms")

    non_doc = [p.name for p in paths if not results[p].is_document]
    if non_doc:
        print(f"\nNOT classified as documents (excluded from matching): {', '.join(non_doc)}")

    docs = [p for p in paths if results[p].is_document]
    same_scores, diff_scores, wrong = [], [], []
    for a, b in itertools.combinations(docs, 2):
        m = matches(results[a].tokens, results[b].tokens)
        expect_same = group_of(a) == group_of(b)
        (same_scores if expect_same else diff_scores).append((m.token_jaccard, a.name, b.name))
        if m.matched != expect_same:
            wrong.append((a.name, b.name, expect_same, m))

    print(f"\n{len(docs)} documents, {len(same_scores)} same-document pairs, {len(diff_scores)} different-document pairs")
    if same_scores:
        lo = min(same_scores)
        print(f"  SAME  token overlap: min={lo[0]:.3f} ({lo[1]} vs {lo[2]})")
    if diff_scores:
        hi = max(diff_scores)
        print(f"  DIFF  token overlap: max={hi[0]:.3f} ({hi[1]} vs {hi[2]})")
    if same_scores and diff_scores:
        gap = min(s[0] for s in same_scores) - max(s[0] for s in diff_scores)
        print(f"  token-only gap: {gap:+.3f} {'(clean)' if gap > 0 else '(OVERLAP — digit rule is carrying the separation)'}")

    print(f"\nverdicts under the shipped rule: {len(same_scores) + len(diff_scores) - len(wrong)}"
          f"/{len(same_scores) + len(diff_scores)} correct")
    for a, b, expect_same, m in wrong:
        dj = f"{m.digit_jaccard:.3f}" if m.digit_jaccard is not None else "n/a"
        kind = "MISSED same document" if expect_same else "FALSE MERGE"
        print(f"  {kind}: {a} vs {b} (token={m.token_jaccard:.3f} digit={dj})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    main(args.folder)
