"""POST /rag-suggest: a visible, dismissible guess — never grounds anything.

Unlike the removed automatic-grounding path, this endpoint never touches
run_chat_pipeline; it just calls rag_service.retrieve() and reports the top
candidate (or nothing) for the chat composer to show. Mirrors the stubbing
style of test_rag_reference_pipeline.py.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import rag_documents_public

_AUTH = {"Authorization": "Bearer test-key", "X-DejaQ-Department": "eng"}


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


class _Chunk:
    def __init__(self, text, title="Building 7 Access Procedures", distance=0.28, doc_id=7):
        self.text = text
        self.title = title
        self.distance = distance
        self.rag_document_id = doc_id
        self.chunk_index = 0


def _post(query: str):
    return TestClient(app, headers=_AUTH).post("/rag-suggest", json={"query": query})


def test_a_matching_question_returns_the_top_candidate(monkeypatch):
    monkeypatch.setattr(rag_documents_public, "RAG_ENABLED", True)
    monkeypatch.setattr(rag_documents_public, "RAG_SUGGEST_ENABLED", True)
    monkeypatch.setattr(
        rag_documents_public.rag_service, "retrieve",
        lambda ns, q, k, d: [_Chunk("Building 7 badge codes rotate every 90 days, per security policy.")],
    )

    resp = _post("how often does the badge code rotate?")

    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == 7
    assert body["title"] == "Building 7 Access Procedures"
    assert body["distance"] == pytest.approx(0.28)
    assert "badge codes rotate" in body["snippet"]


def test_no_match_returns_an_empty_suggestion(monkeypatch):
    monkeypatch.setattr(rag_documents_public, "RAG_ENABLED", True)
    monkeypatch.setattr(rag_documents_public, "RAG_SUGGEST_ENABLED", True)
    monkeypatch.setattr(rag_documents_public.rag_service, "retrieve", lambda ns, q, k, d: [])

    resp = _post("what's the weather like in Marbella?")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"document_id": None, "title": None, "snippet": None, "distance": None}


def test_rag_disabled_never_calls_retrieve(monkeypatch):
    monkeypatch.setattr(rag_documents_public, "RAG_ENABLED", False)
    monkeypatch.setattr(rag_documents_public, "RAG_SUGGEST_ENABLED", True)

    def _boom(*a, **k):
        raise AssertionError("retrieve() must not run when RAG_ENABLED is false")

    monkeypatch.setattr(rag_documents_public.rag_service, "retrieve", _boom)

    resp = _post("a perfectly reasonable question")

    assert resp.status_code == 200
    assert resp.json()["document_id"] is None


def test_suggest_disabled_independently_of_rag_enabled(monkeypatch):
    """RAG_ENABLED alone must not be enough — this is its own switch."""
    monkeypatch.setattr(rag_documents_public, "RAG_ENABLED", True)
    monkeypatch.setattr(rag_documents_public, "RAG_SUGGEST_ENABLED", False)

    def _boom(*a, **k):
        raise AssertionError("retrieve() must not run when RAG_SUGGEST_ENABLED is false")

    monkeypatch.setattr(rag_documents_public.rag_service, "retrieve", _boom)

    resp = _post("a perfectly reasonable question")

    assert resp.status_code == 200
    assert resp.json()["document_id"] is None


def test_too_short_a_query_never_calls_retrieve(monkeypatch):
    monkeypatch.setattr(rag_documents_public, "RAG_ENABLED", True)
    monkeypatch.setattr(rag_documents_public, "RAG_SUGGEST_ENABLED", True)

    def _boom(*a, **k):
        raise AssertionError("retrieve() must not run below the minimum query length")

    monkeypatch.setattr(rag_documents_public.rag_service, "retrieve", _boom)

    resp = _post("hi")

    assert resp.status_code == 200
    assert resp.json()["document_id"] is None


def test_long_snippet_is_truncated_on_a_word_boundary(monkeypatch):
    monkeypatch.setattr(rag_documents_public, "RAG_ENABLED", True)
    monkeypatch.setattr(rag_documents_public, "RAG_SUGGEST_ENABLED", True)
    long_text = "word " * 100  # far past _SUGGEST_SNIPPET_CHARS
    monkeypatch.setattr(
        rag_documents_public.rag_service, "retrieve",
        lambda ns, q, k, d: [_Chunk(long_text)],
    )

    resp = _post("a perfectly reasonable question")

    snippet = resp.json()["snippet"]
    assert len(snippet) <= rag_documents_public._SUGGEST_SNIPPET_CHARS + 1  # +1 for the ellipsis
    assert snippet.endswith("…")
    assert not snippet.endswith("wor…")  # never cuts mid-word
