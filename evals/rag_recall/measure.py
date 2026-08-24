"""RAG retrieval recall/precision/latency measurement.

Run from server/ (reuses its venv — same pattern as image_similarity/gate_eval.py):

    cd server && uv run python ../evals/rag_recall/measure.py [ann|exhaustive|both] [--namespace NS]

Point DEJAQ_CHROMA_HOST / DEJAQ_CHROMA_PORT at an isolated Chroma instance
before running (never a shared one — see the project's testing-isolation rules).

Builds the synthetic corpus in corpus.py (planted facts, disjoint filler
topics, one document ~80% of chunks) and indexes it into a scratch RAG
namespace, then for each of the 15 questions + 5 distractors:
  - runs rag_service.retrieve() (whichever code path is currently wired up)
  - grades recall@1 / recall@top_k against the question's true source document
  - grades precision: did a distractor wrongly inject a chunk
  - times the call

Also reports the TRUE nearest chunk (exhaustive, brute-force over the whole
collection) per question, independent of whatever retrieve() returns, so a
miss can be classified as "crowded out" (true match was inside the distance
gate but retrieve() didn't return it) vs "genuinely too far".
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from corpus import DISTRACTOR_QUESTIONS, QUESTIONS, build_corpus  # noqa: E402

from app.services import rag_service  # noqa: E402

TOP_K = 4
MAX_DISTANCE = 0.35


def index_corpus(namespace: str) -> dict[str, int]:
    """Index the synthetic corpus; returns {doc_key: rag_document_id}."""
    docs = build_corpus()
    doc_ids: dict[str, int] = {}
    for i, doc in enumerate(docs, start=1):
        chunks = rag_service.chunk_text(doc.text)
        rag_service.index_document(
            namespace, i, chunks,
            workspace_slug="ragrecall-eval", title=doc.title, kind="text", source_ref=None,
        )
        doc_ids[doc.key] = i
        print(f"  indexed doc_id={i} key={doc.key!r} chunks={len(chunks)}")
    return doc_ids


def true_nearest(namespace: str, query: str) -> tuple[int, float]:
    """Exhaustive brute-force nearest chunk's rag_document_id and distance,
    independent of retrieve()'s own logic — the measurement ground truth."""
    import numpy as np

    from app.services.memory_chromaDB import embed_text

    collection = rag_service.get_rag_collection(namespace)
    count = collection.count()
    got = collection.get(include=["embeddings", "metadatas"], limit=count)
    embeddings = np.array(got["embeddings"], dtype=np.float32)
    q = np.array(embed_text(query), dtype=np.float32)
    distances = 1.0 - (embeddings @ q)
    idx = int(np.argmin(distances))
    meta = got["metadatas"][idx]
    return int(meta["rag_document_id"]), float(distances[idx])


def run(namespace: str, doc_ids: dict[str, int], label: str) -> dict:
    key_by_id = {v: k for k, v in doc_ids.items()}
    hits_at_1 = 0
    hits_at_k = 0
    misses: list[dict] = []
    latencies_ms: list[float] = []
    for q in QUESTIONS:
        t0 = time.perf_counter()
        chunks = rag_service.retrieve(namespace, q.text, TOP_K, MAX_DISTANCE)
        latencies_ms.append((time.perf_counter() - t0) * 1000)
        target_id = doc_ids[q.doc_key]
        returned_ids = [c.rag_document_id for c in chunks]
        top1_ok = bool(returned_ids) and returned_ids[0] == target_id
        topk_ok = target_id in returned_ids
        hits_at_1 += int(top1_ok)
        hits_at_k += int(topk_ok)
        if not topk_ok:
            true_id, true_dist = true_nearest(namespace, q.text)
            misses.append({
                "question": q.text, "kind": q.kind, "expected_doc": q.doc_key,
                "returned_docs": [key_by_id.get(i, i) for i in returned_ids],
                "true_nearest_doc": key_by_id.get(true_id, true_id),
                "true_nearest_distance": round(true_dist, 4),
                "crowded_out": true_id == target_id and true_dist <= MAX_DISTANCE,
            })

    false_positives = 0
    for dq in DISTRACTOR_QUESTIONS:
        t0 = time.perf_counter()
        chunks = rag_service.retrieve(namespace, dq, TOP_K, MAX_DISTANCE)
        latencies_ms.append((time.perf_counter() - t0) * 1000)
        if chunks:
            false_positives += 1

    n = len(QUESTIONS)
    latencies_sorted = sorted(latencies_ms)

    def pct(p: float) -> float:
        idx = min(len(latencies_sorted) - 1, int(len(latencies_sorted) * p))
        return latencies_sorted[idx]

    result = {
        "label": label,
        "recall_at_1": f"{hits_at_1}/{n} ({100*hits_at_1/n:.0f}%)",
        "recall_at_top_k": f"{hits_at_k}/{n} ({100*hits_at_k/n:.0f}%)",
        "false_positives": f"{false_positives}/{len(DISTRACTOR_QUESTIONS)}",
        "latency_p50_ms": round(pct(0.50), 1),
        "latency_p95_ms": round(pct(0.95), 1),
        "misses": misses,
    }
    return result


def print_result(result: dict) -> None:
    print(f"\n=== {result['label']} ===")
    print(f"recall@1:      {result['recall_at_1']}")
    print(f"recall@top{TOP_K}:   {result['recall_at_top_k']}")
    print(f"false positives (distractors that injected a chunk): {result['false_positives']}")
    print(f"latency p50/p95: {result['latency_p50_ms']}ms / {result['latency_p95_ms']}ms")
    if result["misses"]:
        print("misses:")
        for m in result["misses"]:
            tag = "CROWDED OUT" if m["crowded_out"] else "genuinely too far"
            print(
                f"  - [{m['kind']}] {m['question']!r}\n"
                f"      expected={m['expected_doc']} returned={m['returned_docs']} "
                f"true_nearest={m['true_nearest_doc']}@{m['true_nearest_distance']} ({tag})"
            )


if __name__ == "__main__":
    namespace = "ragrecall-eval__rag_kb"
    for arg in sys.argv[1:]:
        if arg.startswith("--namespace="):
            namespace = arg.split("=", 1)[1]

    print(f"Indexing corpus into namespace={namespace!r} ...")
    doc_ids = index_corpus(namespace)
    total_chunks = rag_service.get_rag_collection(namespace).count()
    print(f"Total chunks in collection: {total_chunks}")

    result = run(namespace, doc_ids, label=f"retrieve() @ {total_chunks} chunks")
    print_result(result)
