"""Does a where-filtered, single-document query reliably find the true best
chunk WITHIN that document?

Scope pivot: automatic whole-collection retrieval is going behind a
default-off flag (another worker, fm/dejaq-rag-at-reference). The live path
going forward is explicit reference: a user names one document, and
retrieval must rank chunks WITHIN that document only. A large referenced
document (thousands of chunks) sitting inside a bigger shared workspace
collection could still have its own internal HNSW recall problem even when
`where`-filtered to just its own chunks — this measures whether that's real.

Reuses the corpus already indexed by measure.py (same namespace, no
re-embedding) — run measure.py first if the namespace is empty.

Run from server/:
    cd server && DEJAQ_CHROMA_HOST=127.0.0.1 DEJAQ_CHROMA_PORT=8911 \
        uv run python ../evals/rag_recall/measure_within_document.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

import numpy as np  # noqa: E402
from corpus import QUESTIONS, build_corpus  # noqa: E402

from app.services import rag_service  # noqa: E402
from app.services.memory_chromaDB import embed_text  # noqa: E402

TOP_K = 4
MAX_DISTANCE = 0.35


def true_nearest_within_document(collection, rag_document_id: int, query_embedding) -> tuple[str, float]:
    """Exhaustive ground truth restricted to one document's own chunks."""
    got = collection.get(where={"rag_document_id": rag_document_id}, include=["embeddings"])
    if not got["ids"]:
        return "", 1.0
    embeddings = np.asarray(got["embeddings"], dtype=np.float32)
    q = np.asarray(query_embedding, dtype=np.float32)
    distances = 1.0 - (embeddings @ q)
    idx = int(np.argmin(distances))
    return got["ids"][idx], float(distances[idx])


def ann_within_document(collection, rag_document_id: int, query_embedding, top_k: int) -> tuple[list, list]:
    """collection.query() with a where filter — what the reference feature
    would call if it just adds `where=` to the existing ANN search."""
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"rag_document_id": rag_document_id},
        include=["distances"],
    )
    if not (results["ids"] and results["ids"][0]):
        return [], []
    return results["ids"][0], results["distances"][0]


def main() -> None:
    namespace = "ragrecall-eval__rag_kb"
    collection = rag_service.get_rag_collection(namespace)
    if collection.count() == 0:
        print(f"Namespace {namespace!r} is empty — run measure.py first.")
        sys.exit(1)

    docs = build_corpus()
    doc_ids = {doc.key: i for i, doc in enumerate(docs, start=1)}
    doc_chunk_counts = {}
    for key, doc_id in doc_ids.items():
        doc_chunk_counts[key] = len(collection.get(where={"rag_document_id": doc_id}, include=[])["ids"])

    print(f"Document chunk counts: {doc_chunk_counts}\n")

    hits_top1 = 0
    hits_topk = 0
    latencies_ms = []
    misses = []
    for q in QUESTIONS:
        target_id = doc_ids[q.doc_key]
        qe = embed_text(q.text)

        true_id, true_dist = true_nearest_within_document(collection, target_id, qe)

        t0 = time.perf_counter()
        ann_ids, ann_dists = ann_within_document(collection, target_id, qe, TOP_K)
        latencies_ms.append((time.perf_counter() - t0) * 1000)

        top1_ok = bool(ann_ids) and ann_ids[0] == true_id
        topk_ok = true_id in ann_ids
        hits_top1 += int(top1_ok)
        hits_topk += int(topk_ok)
        if not topk_ok:
            misses.append({
                "question": q.text, "doc": q.doc_key, "doc_chunks": doc_chunk_counts[q.doc_key],
                "true_best_id": true_id, "true_best_distance": round(true_dist, 4),
                "ann_returned_ids": ann_ids, "ann_returned_distances": [round(d, 4) for d in ann_dists],
            })

    n = len(QUESTIONS)
    s = sorted(latencies_ms)
    p50 = s[len(s) // 2]
    p95 = s[min(len(s) - 1, int(len(s) * 0.95))]

    print(f"within-document recall@1:      {hits_top1}/{n} ({100*hits_top1/n:.0f}%)")
    print(f"within-document recall@top{TOP_K}:   {hits_topk}/{n} ({100*hits_topk/n:.0f}%)")
    print(f"latency (where-filtered ANN) p50/p95: {p50:.1f}ms / {p95:.1f}ms")
    if misses:
        print("\nmisses (true best chunk NOT in the where-filtered ANN top-k):")
        for m in misses:
            print(
                f"  - [{m['doc']} ({m['doc_chunks']} chunks)] {m['question']!r}\n"
                f"      true_best={m['true_best_id']}@{m['true_best_distance']} "
                f"ann_returned={list(zip(m['ann_returned_ids'], m['ann_returned_distances']))}"
            )


if __name__ == "__main__":
    main()
