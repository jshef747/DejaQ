"""What the SHIPPED gate actually does to a corpus.

protocol.py answers a research question — could some scoring function separate
these images? This answers the operational one: run the code that is in
server/app over every pair and count what a user would receive.

Every rule and every constant is imported from the application, never restated
here, so this file cannot drift from what ships.

Three numbers matter, in this order:
  FALSE MERGE  two different images served each other's answer. Unrecoverable.
  recall       same content correctly served. A miss costs one API call.
  routing      which path each image took, because an image refused at routing
               can never hit no matter how good the matching is.

    uv run python ../evals/image_similarity/gate_report.py feat_photos.jsonl
    uv run python ../evals/image_similarity/gate_report.py feat_*.jsonl
"""
from __future__ import annotations

import base64
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app.config import (  # noqa: E402
    CACHE_IMAGE_MAX_DISTANCE,
    CACHE_IMAGE_MAX_HAMMING,
    CACHE_IMAGE_MIN_TILE_VARIETY,
)
from app.services.image_text import OcrResult, matches  # noqa: E402


def kind(rec: dict) -> str:
    """The router's verdict, from the application's own predicates."""
    ocr = OcrResult(frozenset(rec["tokens"]), rec["word_count"],
                    rec["mean_confidence"], ok=True)
    if ocr.is_document:
        return "document"
    if ocr.is_ambiguous:
        return "ambiguous"
    if rec.get("tiles") and len(set(rec["tiles"])) < CACHE_IMAGE_MIN_TILE_VARIETY:
        return "uniform"       # refused before any comparison
    if not rec.get("clip"):
        return "unfingerprintable"
    return "photo"


def _merge_duplicate_groups(recs: list[dict]) -> int:
    """Collapse groups that contain the identical image, and report how many.

    Public corpora contain filing errors: INRIA Holidays stores three
    byte-identical photos under both scene 1031 and scene 1039. Counting those
    as false merges would be scoring the gate against a wrong label — serving
    one for the other is the correct answer. Identical fingerprints mean
    identical bytes, so no file access is needed.
    """
    parent: dict[str, str] = {}

    def find(g: str) -> str:
        while parent.setdefault(g, g) != g:
            g = parent[g] = parent[parent[g]]
        return g

    by_image: dict[tuple, str] = {}
    merged = 0
    for r in recs:
        key = (r.get("dhash"), r.get("clip"), tuple(r["tokens"]))
        if key[0] is None and key[1] is None:
            continue
        first = by_image.setdefault(key, r["group"])
        a, b = find(first), find(r["group"])
        if a != b:
            parent[b] = a
            merged += 1
    for r in recs:
        r["group"] = find(r["group"])
    return merged


def load(path: Path) -> list[dict]:
    recs = []
    for line in path.open():
        r = json.loads(line)
        r["token_set"] = frozenset(r["tokens"])
        r["kind"] = kind(r)
        r["vec"] = (np.frombuffer(base64.b64decode(r["clip"]), dtype=np.float32)
                    if r.get("clip") else None)
        r["dh"] = int(r["dhash"], 16) if r.get("dhash") else None
        recs.append(r)
    dupes = _merge_duplicate_groups(recs)
    if dupes:
        print(f"[{path.name}] collapsed {dupes} label groups holding identical images")
    return recs


def decide(a: dict, b: dict) -> tuple[bool, str]:
    """Serve or refuse, and why. Mirrors _evaluate_image_gate in the router."""
    if a["kind"] != b["kind"]:
        return False, "kind_mismatch"
    if a["kind"] != "document" and a["kind"] != "photo":
        return False, a["kind"]           # ambiguous / uniform: never served
    if a["kind"] == "document":
        m = matches(a["token_set"], b["token_set"])
        return m.matched, "text_pass" if m.matched else "text_mismatch"
    ham = (a["dh"] ^ b["dh"]).bit_count()
    if ham > CACHE_IMAGE_MAX_HAMMING:
        return False, "hamming_exceeded"
    if float(1.0 - np.dot(a["vec"], b["vec"])) > CACHE_IMAGE_MAX_DISTANCE:
        return False, "clip_exceeded"
    return True, "pixel_pass"


def report(path: Path) -> dict:
    recs = load(path)
    groups = {r["group"] for r in recs}
    routing = Counter(r["kind"] for r in recs)

    hits = merges = same = diff = 0
    miss_reason: Counter[str] = Counter()
    merge_examples: list[tuple[str, str, str]] = []
    for a, b in combinations(recs, 2):
        is_same = a["group"] == b["group"]
        served, why = decide(a, b)
        if is_same:
            same += 1
            if served:
                hits += 1
            else:
                miss_reason[why] += 1
        else:
            diff += 1
            if served:
                merges += 1
                if len(merge_examples) < 8:
                    merge_examples.append((a["path"], b["path"], why))

    print(f"\n=== {path.name} ===")
    print(f"{len(recs)} images, {len(groups)} content groups")
    print("routing: " + ", ".join(
        f"{k} {v} ({100 * v / len(recs):.0f}%)" for k, v in routing.most_common()))
    print(f"pairs: {same} same-content, {diff} different-content")
    print(f"  SERVED + same      : {hits:>7}   recall {100 * hits / same if same else 0:.1f}%")
    print(f"  SERVED + different : {merges:>7}   <-- FALSE MERGES")
    # The number a user feels: of the answers the cache DID serve, how many were
    # about something else. Merge counts alone flatter a gate that serves nothing.
    served = hits + merges
    print(f"  wrong answers served: {100 * merges / served if served else 0:.2f}% "
          f"of {served} cache hits")
    if miss_reason:
        print("  missed positives by reason: " + ", ".join(
            f"{k} {v}" for k, v in miss_reason.most_common()))
    for x, y, why in merge_examples:
        print(f"    merge: {x} <-> {y} ({why})")
    return {"corpus": path.name, "images": len(recs), "groups": len(groups),
            "routing": dict(routing), "same": same, "diff": diff,
            "hits": hits, "merges": merges, "miss": dict(miss_reason)}


if __name__ == "__main__":
    paths = [Path(p) for p in sys.argv[1:]] or sorted(Path(__file__).parent.glob("feat_*.jsonl"))
    out = [report(p) for p in paths]
    print("\n=== summary ===")
    print(f"{'corpus':<22}{'images':>7}{'recall':>9}{'merges':>9}")
    for r in out:
        rec = 100 * r["hits"] / r["same"] if r["same"] else 0.0
        print(f"{r['corpus']:<22}{r['images']:>7}{rec:>8.1f}%{r['merges']:>9}")
    (Path(__file__).parent / "gate_report.json").write_text(json.dumps(out, indent=1))
