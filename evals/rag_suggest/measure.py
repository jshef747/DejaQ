"""Suggestion appearance/accuracy/noise measurement.

Run from server/ (reuses its venv, same pattern as rag_recall/measure.py):

    cd server && uv run python ../evals/rag_suggest/measure.py [--distance=0.45] [--namespace NS]

Point DEJAQ_CHROMA_HOST / DEJAQ_CHROMA_PORT at an isolated Chroma instance
first (never a shared one).

Reuses the SAME synthetic corpus rag_recall measured with (5 documents, one
planted fact each, disjoint filler topics, one document ~80% of all chunks) —
"the same style of corpus the earlier reports used" — rather than building a
second one. For each candidate distance threshold, calls the exact function
the /rag-suggest endpoint calls (rag_service.retrieve(ns, query, top_k=1,
max_distance)) and reports, over the 15 in-KB questions and 5 distractors:

  - appearance rate: how often a suggestion comes back at all (15 questions)
  - accuracy given appearance: of those, how often it names the right document
  - noise rate: how often a suggestion appears for an unanswerable question
    (the 5 distractors — the false-positive case)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rag_recall"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from corpus import DISTRACTOR_QUESTIONS, QUESTIONS, build_corpus  # noqa: E402

from app.services import rag_service  # noqa: E402


def index_corpus(namespace: str) -> dict[str, int]:
    docs = build_corpus()
    doc_ids: dict[str, int] = {}
    for i, doc in enumerate(docs, start=1):
        chunks = rag_service.chunk_text(doc.text)
        rag_service.index_document(
            namespace, i, chunks,
            workspace_slug="ragsuggest-eval", title=doc.title, kind="text", source_ref=None,
        )
        doc_ids[doc.key] = i
        print(f"  indexed doc_id={i} key={doc.key!r} chunks={len(chunks)}")
    return doc_ids


def measure_at(namespace: str, doc_ids: dict[str, int], max_distance: float) -> dict:
    appeared = 0
    correct = 0
    detail: list[str] = []
    for q in QUESTIONS:
        chunks = rag_service.retrieve(namespace, q.text, 1, max_distance)
        target_id = doc_ids[q.doc_key]
        if chunks:
            appeared += 1
            ok = chunks[0].rag_document_id == target_id
            correct += int(ok)
            tag = "OK" if ok else f"WRONG (got doc_id={chunks[0].rag_document_id})"
            detail.append(f"    [{q.kind}] {tag} dist={chunks[0].distance:.4f} {q.text!r}")
        else:
            detail.append(f"    [{q.kind}] no suggestion {q.text!r}")

    noisy = 0
    noise_detail: list[str] = []
    for dq in DISTRACTOR_QUESTIONS:
        chunks = rag_service.retrieve(namespace, dq, 1, max_distance)
        if chunks:
            noisy += 1
            noise_detail.append(f"    dist={chunks[0].distance:.4f} {dq!r} -> doc_id={chunks[0].rag_document_id}")

    n = len(QUESTIONS)
    nd = len(DISTRACTOR_QUESTIONS)
    return {
        "max_distance": max_distance,
        "appearance_rate": f"{appeared}/{n} ({100*appeared/n:.0f}%)",
        "accuracy_when_appeared": (
            f"{correct}/{appeared} ({100*correct/appeared:.0f}%)" if appeared else "n/a (never appeared)"
        ),
        "noise_rate": f"{noisy}/{nd} ({100*noisy/nd:.0f}%)",
        "detail": detail,
        "noise_detail": noise_detail,
    }


def print_result(result: dict) -> None:
    print(f"\n=== max_distance={result['max_distance']} ===")
    print(f"appearance rate (of {len(QUESTIONS)} in-KB questions):      {result['appearance_rate']}")
    print(f"accuracy when it appeared:                                  {result['accuracy_when_appeared']}")
    print(f"noise rate (of {len(DISTRACTOR_QUESTIONS)} unanswerable questions):        {result['noise_rate']}")
    print("  per-question:")
    for line in result["detail"]:
        print(line)
    if result["noise_detail"]:
        print("  noise (distractor got a suggestion anyway):")
        for line in result["noise_detail"]:
            print(line)


if __name__ == "__main__":
    namespace = "ragsuggest-eval__rag_kb"
    distances = [0.35, 0.45, 0.55, 0.65]
    for arg in sys.argv[1:]:
        if arg.startswith("--namespace="):
            namespace = arg.split("=", 1)[1]
        elif arg.startswith("--distance="):
            distances = [float(arg.split("=", 1)[1])]

    print(f"Indexing corpus into namespace={namespace!r} ...")
    doc_ids = index_corpus(namespace)
    total_chunks = rag_service.get_rag_collection(namespace).count()
    print(f"Total chunks in collection: {total_chunks}")

    for d in distances:
        print_result(measure_at(namespace, doc_ids, d))
