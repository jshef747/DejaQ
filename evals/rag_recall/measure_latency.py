"""Latency scaling of exhaustive vs ANN RAG retrieval, at increasing chunk counts.

Pure latency measurement, deliberately decoupled from real text: an
exhaustive scan's cost is `collection.get(embeddings)` (I/O bound by vector
count) plus one matmul (compute bound by count x dim). Neither depends on
what the vectors mean, so synthetic random unit vectors let this scale to
sizes (100k+ chunks) that would take a real embedding model far too long to
produce here, without changing what's actually being timed. Recall/precision
at realistic size is measured separately in measure.py, on real text.

Run from server/, pointed at an isolated Chroma instance:

    cd server && DEJAQ_CHROMA_HOST=127.0.0.1 DEJAQ_CHROMA_PORT=8911 \
        uv run python ../evals/rag_recall/measure_latency.py
"""
from __future__ import annotations

import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

import numpy as np  # noqa: E402

from app.services import rag_service  # noqa: E402
from app.services.memory_chromaDB import embed_text  # noqa: E402

SIZES = [5_000, 20_000, 50_000, 100_000]
TOP_K = 4
N_QUERIES = 10
BATCH = 2000


def build_synthetic_namespace(namespace: str, n: int, dim: int, rng: random.Random) -> None:
    collection = rag_service.get_rag_collection(namespace)
    written = 0
    while written < n:
        batch_n = min(BATCH, n - written)
        vecs = np.random.default_rng(rng.randint(0, 2**31)).normal(size=(batch_n, dim)).astype(np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        ids = [f"999:{written + i}" for i in range(batch_n)]
        metadatas = [
            {"rag_document_id": 999, "workspace_slug": "latency-eval", "title": "synthetic",
             "kind": "text", "source_ref": "", "chunk_index": written + i, "stored_at": ""}
            for i in range(batch_n)
        ]
        documents = ["synthetic chunk text" for _ in range(batch_n)]
        collection.upsert(ids=ids, embeddings=vecs.tolist(), documents=documents, metadatas=metadatas)
        written += batch_n
    print(f"  wrote {written} synthetic vectors (dim={dim})")


def time_calls(fn, n_calls: int) -> list[float]:
    out = []
    for _ in range(n_calls):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def summarize(label: str, latencies_ms: list[float]) -> None:
    s = sorted(latencies_ms)
    p50 = s[len(s) // 2]
    p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
    print(f"  {label:22} p50={p50:8.1f}ms  p95={p95:8.1f}ms  mean={statistics.mean(s):8.1f}ms")


def main() -> None:
    rng = random.Random(20260822)
    q = embed_text("a representative query used for latency timing only")
    dim = len(q)

    for n in SIZES:
        namespace = f"latency-eval-{n}__rag_kb"
        print(f"\n=== {n} chunks ===")
        build_synthetic_namespace(namespace, n, dim, rng)
        collection = rag_service.get_rag_collection(namespace)

        exhaustive_ms = time_calls(
            lambda: rag_service._exhaustive_query(collection, q, TOP_K), N_QUERIES
        )
        summarize("exhaustive", exhaustive_ms)

        ann_ms = time_calls(
            lambda: rag_service._ann_query(collection, q, TOP_K), N_QUERIES
        )
        summarize("ann (HNSW)", ann_ms)

        rag_service.delete_namespace(namespace)


if __name__ == "__main__":
    main()
