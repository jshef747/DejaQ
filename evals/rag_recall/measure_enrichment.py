"""Does the context enricher's rewrite hurt RAG retrieval in a multi-turn chat?

Reproduces the report's live finding (section 3.4): a follow-up question,
after the enricher (Qwen 1.5B) rewrites it into a standalone form, can lose
retrieval it would have found on the raw text. Measures retrieve() against
(a) the enriched+normalized text (production today), (b) the raw original
user text, and (c) the union of both, on the same corpus as measure.py.

Run from server/, pointed at the same isolated Chroma the corpus was already
indexed into, and at the shared Ollama for the enricher:

    cd server && DEJAQ_CHROMA_HOST=127.0.0.1 DEJAQ_CHROMA_PORT=8911 \
        uv run python ../evals/rag_recall/measure_enrichment.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from corpus import build_corpus  # noqa: E402

from app.config import ENRICHER_MODEL_NAME, OLLAMA_TIMEOUT_SECONDS, OLLAMA_URL  # noqa: E402
from app.services import rag_service  # noqa: E402
from app.services.context_enricher import ContextEnricherService  # noqa: E402
from app.services.model_backends import OllamaBackend  # noqa: E402

TOP_K = 4
MAX_DISTANCE = 0.35

# Multi-turn scenarios: unrelated small talk, THEN a follow-up whose standalone
# meaning depends on nothing in history (so a good enricher should barely
# touch it) but whose exact wording risks being rewritten into something that
# drifts from the phrasing retrieval originally found. Mirrors the report's
# live case: "Tell me about the product roadmap." asked cold retrieves fine;
# asked as a follow-up, the enricher's paraphrase lost it.
SCENARIOS = [
    {
        "doc_key": "product_roadmap",
        "history": [
            {"role": "user", "content": "Hey, how's your day going?"},
            {"role": "assistant", "content": "Going well, thanks for asking! How can I help?"},
        ],
        "follow_up": "Tell me about the product roadmap.",
    },
    {
        "doc_key": "onboarding_handbook",
        "history": [
            {"role": "user", "content": "I just accepted the offer, excited to start!"},
            {"role": "assistant", "content": "Congratulations! Welcome aboard."},
        ],
        "follow_up": "What training do I need to finish?",
    },
    {
        "doc_key": "badge_procedures",
        "history": [
            {"role": "user", "content": "I'll be visiting Building 7 next week."},
            {"role": "assistant", "content": "Got it, I can help with anything about that visit."},
        ],
        "follow_up": "How does access work there?",
    },
]


async def main() -> None:
    namespace = "ragrecall-eval__rag_kb"
    docs = build_corpus()
    doc_ids = {}
    collection = rag_service.get_rag_collection(namespace)
    if collection.count() == 0:
        print("Namespace empty — indexing corpus (measure.py normally does this).")
        for i, doc in enumerate(docs, start=1):
            chunks = rag_service.chunk_text(doc.text)
            rag_service.index_document(
                namespace, i, chunks, workspace_slug="ragrecall-eval",
                title=doc.title, kind="text", source_ref=None,
            )
            doc_ids[doc.key] = i
    else:
        doc_ids = {doc.key: i for i, doc in enumerate(docs, start=1)}

    backend = OllamaBackend(base_url=OLLAMA_URL, timeout_seconds=OLLAMA_TIMEOUT_SECONDS)
    enricher = ContextEnricherService(backend=backend, model_name=ENRICHER_MODEL_NAME)

    print(f"\n{'scenario':30} {'enriched_recall':16} {'original_recall':16} {'union_recall':14} enriched_text")
    enriched_hits = original_hits = union_hits = 0
    for sc in SCENARIOS:
        enriched = await enricher.enrich(sc["follow_up"], sc["history"])
        target_id = doc_ids[sc["doc_key"]]

        e_chunks = rag_service.retrieve(namespace, enriched, TOP_K, MAX_DISTANCE)
        o_chunks = rag_service.retrieve(namespace, sc["follow_up"], TOP_K, MAX_DISTANCE)
        union_ids = {c.rag_document_id for c in e_chunks} | {c.rag_document_id for c in o_chunks}

        e_ok = target_id in {c.rag_document_id for c in e_chunks}
        o_ok = target_id in {c.rag_document_id for c in o_chunks}
        u_ok = target_id in union_ids
        enriched_hits += int(e_ok)
        original_hits += int(o_ok)
        union_hits += int(u_ok)

        print(f"{sc['doc_key']:30} {str(e_ok):16} {str(o_ok):16} {str(u_ok):14} {enriched!r}")

    n = len(SCENARIOS)
    print(f"\nenriched-only recall: {enriched_hits}/{n}")
    print(f"original-only recall: {original_hits}/{n}")
    print(f"union recall:         {union_hits}/{n}")


if __name__ == "__main__":
    asyncio.run(main())
