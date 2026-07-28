"""Shared scoring protocol. Every candidate approach is judged by this, unchanged.

A candidate is a function  score(a, b) -> float  over two feature records.
Higher must mean "more likely the same content".

The judgement:
  - a FALSE MERGE (two different documents served each other's answer) is the
    only unrecoverable error; a miss just costs a cache miss.
  - so: sweep the candidate's own threshold, find the highest threshold-free
    recall achievable at ZERO false merges, and also report the recall at a
    small non-zero merge budget so the trade-off is visible.

Baseline to beat: plain token-set Jaccard, which achieves
    45.4% recall at 0 false merges (threshold 0.80)
    77.9% recall at 114 merges (threshold 0.70)
"""
from __future__ import annotations

import base64
import json
from itertools import combinations
from pathlib import Path

import numpy as np

FEATURES = Path(__file__).parent / "features_rich.jsonl"


def load(only_documents: bool = True, conf_floor: float = 80.0, word_floor: int = 25) -> list[dict]:
    """Load feature records. By default keeps only images the shipped router
    calls documents, which is the population the document rule must serve."""
    recs = []
    for line in FEATURES.open():
        r = json.loads(line)
        r["token_set"] = frozenset(r["tokens"])
        r["clip_vec"] = (
            np.frombuffer(base64.b64decode(r["clip"]), dtype=np.float32) if r.get("clip") else None
        )
        r["dhash_int"] = int(r["dhash"], 16) if r.get("dhash") else None
        if only_documents and not (
            r["mean_confidence"] >= conf_floor and r["word_count"] >= word_floor
        ):
            continue
        recs.append(r)
    return recs


def pairs(recs: list[dict]) -> list[tuple[dict, dict, bool]]:
    """All pairs with ground truth: same content group -> True."""
    return [(a, b, a["group"] == b["group"]) for a, b in combinations(recs, 2)]


def evaluate(recs: list[dict], score, name: str, merge_budgets=(0, 5, 25)) -> dict:
    """Score every pair, then report recall at each false-merge budget.

    Returns a dict with the headline number: recall at zero false merges.
    """
    ps = pairs(recs)
    scored = [(score(a, b), same, a["path"], b["path"]) for a, b, same in ps]
    n_same = sum(1 for _, same, _, _ in scored if same)
    n_diff = len(scored) - n_same

    # Sort negatives descending: the k-th highest negative score is the threshold
    # that admits exactly k merges.
    neg = sorted((s for s, same, _, _ in scored if not same), reverse=True)
    pos = sorted((s for s, same, _, _ in scored if same), reverse=True)

    out = {"name": name, "n_same": n_same, "n_diff": n_diff, "results": {}}
    for budget in merge_budgets:
        if budget >= len(neg):
            continue
        # Threshold just above the (budget)-th highest negative admits `budget` merges.
        thresh = neg[budget] + 1e-9 if budget < len(neg) else float("-inf")
        served = sum(1 for s in pos if s >= thresh)
        out["results"][budget] = {
            "threshold": round(float(thresh), 4),
            "recall": served / n_same if n_same else 0.0,
            "served": served,
        }
    worst = neg[0] if neg else None
    out["hardest_negative_score"] = round(float(worst), 4) if worst is not None else None
    out["same_score_median"] = round(float(pos[len(pos) // 2]), 4) if pos else None
    return out


def report(result: dict) -> None:
    print(f"\n--- {result['name']} ---")
    print(f"    {result['n_same']} same-content pairs, {result['n_diff']} different")
    print(f"    hardest negative scores {result['hardest_negative_score']}, "
          f"median same-content {result['same_score_median']}")
    print(f"    {'merges':>7} {'threshold':>10} {'recall':>8}")
    for budget, r in sorted(result["results"].items()):
        print(f"    {budget:>7} {r['threshold']:>10.4f} {100 * r['recall']:>7.1f}%")


BASELINE_ZERO_MERGE_RECALL = 0.454


def token_jaccard(a: dict, b: dict) -> float:
    """The current shipped signal, as the baseline every candidate must beat."""
    x, y = a["token_set"], b["token_set"]
    u = x | y
    return len(x & y) / len(u) if u else 0.0


if __name__ == "__main__":
    recs = load()
    print(f"{len(recs)} document images, {len({r['group'] for r in recs})} groups")
    report(evaluate(recs, token_jaccard, "BASELINE token-set Jaccard"))
