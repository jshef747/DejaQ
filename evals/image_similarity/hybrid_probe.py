"""Upscale to decide ROUTING only, and keep matching on the original read.

Flat 2x upscaling was measured twice. It lifts recall everywhere and introduces
false merges on three of four corpora, because reading a page more completely
also reads the shared boilerplate of two near-duplicate documents more
completely: two different receipts went from 0.848 overlap to 0.983.

But its gain was not evenly split. Round 2 went 9.9% -> 29.8% recall with ZERO
merges, and the reason is visible in the routing: 227 images were refused as
"ambiguous" (text present, read too badly to trust) and only 41 were after
upscaling. That gain is about deciding *whether* an image is a readable document
— which cannot cause a merge — rather than about what its words are, which can.

So: take the KIND from the upscaled read and the TOKENS from the original one.
Pure recombination of feature files that already exist, no new OCR.

    uv run python ../evals/image_similarity/hybrid_probe.py receipts screens r1 r2
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from gate_report import decide, load  # noqa: E402

HERE = Path(__file__).parent


def score(recs: list[dict]) -> tuple[int, int, int]:
    hits = merges = same = 0
    for a, b in combinations(recs, 2):
        served = decide(a, b)[0]
        if a["group"] == b["group"]:
            same += 1
            hits += served
        else:
            merges += served
    return hits, merges, same


def run(name: str) -> None:
    plain = {r["path"]: r for r in load(HERE / f"feat_{name}.jsonl")}
    up = {r["path"]: r for r in load(HERE / f"feat_{name}_2x.jsonl")}
    shared = [p for p in plain if p in up]

    variants = {
        "shipped": [plain[p] for p in shared],
        "upscaled": [up[p] for p in shared],
        # kind from the upscaled read, everything used for matching from the original
        "hybrid": [{**plain[p], "kind": up[p]["kind"]} for p in shared],
    }
    print(f"\n=== {name} ({len(shared)} images) ===")
    print(f"{'variant':<12}{'recall':>9}{'merges':>9}{'wrong/hit':>11}")
    for label, recs in variants.items():
        hits, merges, same = score(recs)
        served = hits + merges
        print(f"{label:<12}{100 * hits / same if same else 0:>8.1f}%{merges:>9}"
              f"{100 * merges / served if served else 0:>10.2f}%")


if __name__ == "__main__":
    for corpus in sys.argv[1:] or ["receipts", "screens", "r1", "r2"]:
        run(corpus)
