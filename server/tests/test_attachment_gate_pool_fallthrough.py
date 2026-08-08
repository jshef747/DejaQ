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
                distance=0.03, matched_query=QUESTION, file_sha=SHA_B, file_kind="pdf",
            ),
            CacheLookupResult(
                hit=True, generalized_answer=ANSWER_A, entry_id="doc-a",
                distance=0.03, matched_query=QUESTION, file_sha=SHA_A, file_kind="pdf",
            ),
        ]
        return candidates, 0.03, QUESTION

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
        lambda profile: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=None,
            adjuster=StubAdjuster(), enricher=StubEnricher(), validator=None,
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


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
