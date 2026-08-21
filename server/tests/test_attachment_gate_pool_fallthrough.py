"""Attachment-gate pool fallthrough — the fix for the defect described in
docs: `lookup_cache` used to return exactly one candidate, so a gate REJECT on
that single winner became a full cache miss even when a validly cached
sibling entry existed in the pool. Two documents sharing one question
("summarise this document") is the reproducing case: they can tie or win the
score ranking arbitrarily, so a request carrying document A could permanently
land on B's entry, get REJECTed, and never see its own cached answer again.

These exercise the real pipeline (router -> pool -> gate) with a stubbed
memory whose `lookup_cache_pool` returns both entries, B ranked ahead of A to
simulate B winning the tie.
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services import file_text
from app.services.memory_chromaDB import CacheLookupResult
from tests.test_file_gate import make_pdf
from tests.test_file_hit_pipeline import _patch_external_provider
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
)

QUESTION = "summarise this document"
ANSWER_A = "Document A is a purchase agreement between Acme and Beta."
ANSWER_B = "Document B is a lease renewal for the downtown office."

TEXT_A = " ".join(f"clause{i}" for i in range(45))
TEXT_B = " ".join(f"other-clause{i}" for i in range(45))
TEXT_C = " ".join(f"unrelated-clause{i}" for i in range(45))

PDF_A = make_pdf(TEXT_A)
PDF_B = make_pdf(TEXT_B)
PDF_C = make_pdf(TEXT_C)

SHA_A = file_text.extract(PDF_A, "application/pdf", "a.pdf").sha
SHA_B = file_text.extract(PDF_B, "application/pdf", "b.pdf").sha


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class TwoDocumentPoolMemory:
    """Two entries for the SAME question, one per attachment, B ranked first.

    `lookup_cache_pool` is exactly the API the fix added — a ranked list plus
    nearest-diagnostics — mirroring what MemoryService.lookup_cache_pool
    returns for real. Distances sit inside VALIDATOR_SKIP_DISTANCE so the
    validator is not part of what's under test here.
    """

    def lookup_cache_pool(self, clean_query: str):
        candidates = [
            CacheLookupResult(
                hit=True, generalized_answer=ANSWER_B, entry_id="doc-b",
                distance=0.001, matched_query=QUESTION, file_sha=SHA_B, file_kind="pdf",
            ),
            CacheLookupResult(
                hit=True, generalized_answer=ANSWER_A, entry_id="doc-a",
                distance=0.001, matched_query=QUESTION, file_sha=SHA_A, file_kind="pdf",
            ),
        ]
        return candidates, 0.001, QUESTION

    def lookup_cache(self, clean_query: str):
        return self.lookup_cache_pool(clean_query)[0][0]

    def increment_hit_count(self, doc_id: str):
        return None

    def count_file_entries(self, file_sha: str) -> int:
        return 1 if file_sha in (SHA_A, SHA_B) else 0


def _patch_pipeline(monkeypatch, *, memory):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=None,
            adjuster=StubAdjuster(), enricher=StubEnricher(), validator=None,
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(
        openai_compat, "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash", routing_threshold=0.3,
        ),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    _patch_external_provider(monkeypatch, "a fresh answer generated for this document")


def _post(pdf: bytes):
    content = [
        {"type": "input_text", "text": QUESTION},
        {
            "type": "input_file", "filename": "doc.pdf",
            "file_data": "data:application/pdf;base64," + base64.b64encode(pdf).decode(),
        },
    ]
    return TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={"model": "gpt-4o", "input": [{"role": "user", "content": content}], "stream": False},
    )


def test_own_document_served_even_when_a_sibling_wins_the_tie(monkeypatch):
    """PDF A's own entry is served, though B is ranked ahead of it in the pool."""
    _patch_pipeline(monkeypatch, memory=TwoDocumentPoolMemory())

    resp = _post(PDF_A)

    assert resp.headers.get("x-dejaq-tier") == "cache"
    assert resp.json()["output_text"] == ANSWER_A


def test_the_other_document_still_gets_its_own_entry(monkeypatch):
    """Symmetry check: B's own request must not accidentally serve A's answer."""
    _patch_pipeline(monkeypatch, memory=TwoDocumentPoolMemory())

    resp = _post(PDF_B)

    assert resp.headers.get("x-dejaq-tier") == "cache"
    assert resp.json()["output_text"] == ANSWER_B


def test_uncached_document_still_misses(monkeypatch):
    """A document with no entry in the pool must fall through to a full miss,
    not be served either sibling's answer — the pool-exhausted fallback."""
    _patch_pipeline(monkeypatch, memory=TwoDocumentPoolMemory())

    resp = _post(PDF_C)

    assert resp.headers.get("x-dejaq-tier") != "cache"
    assert ANSWER_A not in resp.text
    assert ANSWER_B not in resp.text


IMAGE_TOKENS_A = frozenset(f"alpha{i}" for i in range(10))
IMAGE_TOKENS_B = frozenset(f"bravo{i}" for i in range(10))


class TwoImagePoolMemory:
    """Same shape as TwoDocumentPoolMemory, image side: two scanned pages under
    one question, the wrong one ranked first."""

    def lookup_cache_pool(self, clean_query: str):
        candidates = [
            CacheLookupResult(
                hit=True, generalized_answer=ANSWER_B, entry_id="img-b",
                distance=0.001, matched_query=QUESTION, image_kind="document",
                image_text=" ".join(sorted(IMAGE_TOKENS_B)),
            ),
            CacheLookupResult(
                hit=True, generalized_answer=ANSWER_A, entry_id="img-a",
                distance=0.001, matched_query=QUESTION, image_kind="document",
                image_text=" ".join(sorted(IMAGE_TOKENS_A)),
            ),
        ]
        return candidates, 0.001, QUESTION

    def increment_hit_count(self, doc_id: str):
        return None


def test_own_image_served_even_when_a_sibling_wins_the_tie(monkeypatch):
    """The image gate falls through the same way the file gate does — the pool
    walk is shared, so the photo/document path must not still veto-and-miss."""
    from app.services.image_text import OcrResult

    _patch_pipeline(monkeypatch, memory=TwoImagePoolMemory())
    monkeypatch.setattr(
        openai_compat, "extract_image_text",
        lambda data: OcrResult(IMAGE_TOKENS_A, word_count=200, mean_confidence=90.0, ok=True),
    )

    resp = TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={"model": "gpt-4o", "stream": False, "input": [{"role": "user", "content": [
            {"type": "input_text", "text": QUESTION},
            {"type": "input_image",
             "image_url": "data:image/png;base64," + base64.b64encode(b"PAGE-A").decode()},
        ]}]},
    )

    assert resp.headers.get("x-dejaq-tier") == "cache"
    assert resp.json()["output_text"] == ANSWER_A


def _memory_with_rows(monkeypatch, rows):
    from app.services import memory_chromaDB

    class StubCollection:
        def count(self):
            return len(rows)

        def query(self, **kwargs):
            return {
                "ids": [[r["id"] for r in rows]],
                "distances": [[r["dist"] for r in rows]],
                "documents": [[r.get("doc", QUESTION) for r in rows]],
                "metadatas": [[r["meta"] for r in rows]],
            }

    monkeypatch.setattr(memory_chromaDB, "_embed", lambda text: [0.0])
    service = memory_chromaDB.MemoryService.__new__(memory_chromaDB.MemoryService)
    service._collection = StubCollection()
    return service


def test_pool_spans_all_tiers_with_per_candidate_flags(monkeypatch):
    """Trusted, band, and rescue rows all appear in the pool in tier priority
    order — score-ordered within each tier — each carrying its own tier's
    requires_validation/rescued flags."""
    memory = _memory_with_rows(monkeypatch, [
        {"id": "band-1", "dist": 0.18, "meta": {"generalized_answer": "band", "score": 9.0}},
        {"id": "trusted-low", "dist": 0.05, "meta": {"generalized_answer": "t-low", "score": 1.0}},
        {"id": "rescue-1", "dist": 0.40, "meta": {"generalized_answer": "rescue", "score": 9.0}},
        {"id": "trusted-high", "dist": 0.10, "meta": {"generalized_answer": "t-high", "score": 5.0}},
    ])

    candidates, nearest_dist, nearest_prompt = memory.lookup_cache_pool(QUESTION)

    assert [c.entry_id for c in candidates] == ["trusted-high", "trusted-low", "band-1", "rescue-1"]
    assert [(c.requires_validation, c.rescued) for c in candidates] == [
        (False, False), (False, False), (True, False), (True, True),
    ]
    assert nearest_dist == pytest.approx(0.18)
    assert nearest_prompt == QUESTION


def test_corrupt_entry_skipped_not_fatal(monkeypatch):
    """A row missing generalized_answer metadata is dropped, not a KeyError
    that turns the whole lookup into a miss."""
    memory = _memory_with_rows(monkeypatch, [
        {"id": "corrupt", "dist": 0.03, "meta": {"score": 9.0}},
        {"id": "good", "dist": 0.05, "meta": {"generalized_answer": "fine", "score": 1.0}},
    ])

    candidates, _, _ = memory.lookup_cache_pool(QUESTION)

    assert [c.entry_id for c in candidates] == ["good"]
    assert memory.lookup_cache(QUESTION).entry_id == "good"
