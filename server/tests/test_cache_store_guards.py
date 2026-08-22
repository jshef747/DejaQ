"""Regression guards for two bugs observed in production logs.

1. A failed generation was cached, so the user-facing apology text became a real
   cache answer served to every later match.
2. Image-anchored answers were passed through the generalizer, which cannot see
   the image and invents specifics (a Complex Analysis syllabus was stored as
   "Statistics or Data Analysis Course").
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.memory_chromaDB import CacheLookupResult
from tests.conftest import StreamingLocalRouterMixin
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubMemory,
    StubNormalizer,
)


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    """Make the Bearer token in _AUTH resolve (autouse fixtures don't cross modules)."""
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class ExplodingRouter(StreamingLocalRouterMixin):
    """Local generation fails — the pipeline should answer with an apology and NOT cache it."""

    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
        raise RuntimeError("model unavailable")


class TruncatingRouter(StreamingLocalRouterMixin):
    """Local generation hits the token budget — the answer reaches the user but
    the cut-off text must never be stored (a stored truncation never heals: it
    is what every later match is served, reported as finish_reason=stop)."""

    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
        return "The capital of France is Par", 12.0, "length"


class RecordingMemory(StubMemory):
    def __init__(self):
        self.stored: list[dict] = []

    def store_interaction(self, clean_query, generalized_answer, original_query, user_id, **kw):
        self.stored.append({"query": clean_query, "answer": generalized_answer, **kw})
        return "doc123"


def _patch_common(monkeypatch, memory, router=None):
    async def _noop_log(*a, **k):
        return None

    # The pipeline resolves services through _services_for_model_profile (which
    # reads module-level singletons built at import), so patch that seam.
    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=router,
            adjuster=StubAdjuster(), enricher=StubEnricher(), validator=None,
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def test_failed_generation_is_not_cached(monkeypatch):
    memory = RecordingMemory()
    _patch_common(monkeypatch, memory, ExplodingRouter())

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        headers={"X-DejaQ-Routing-Mode": "easy_local"},
        json={"model": "m", "messages": [{"role": "user", "content": "What is the capital of France?"}], "stream": False},
    )

    assert response.status_code == 200
    assert response.headers["x-dejaq-model-used"] == "error"
    # The apology reached the user but must never have been stored.
    assert memory.stored == [], f"an errored generation was cached: {memory.stored}"
    assert "x-dejaq-response-id" not in response.headers


def test_truncated_generation_is_not_cached(monkeypatch):
    memory = RecordingMemory()
    _patch_common(monkeypatch, memory, TruncatingRouter())

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        headers={"X-DejaQ-Routing-Mode": "easy_local"},
        json={
            "model": "m",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "max_tokens": 8,
            "stream": False,
        },
    )

    assert response.status_code == 200
    # The cut-off answer reached the user, honestly labelled, and was not stored.
    assert response.json()["choices"][0]["finish_reason"] == "length"
    assert memory.stored == [], f"a truncated generation was cached: {memory.stored}"
    assert "x-dejaq-response-id" not in response.headers


def test_image_answers_are_stored_verbatim(monkeypatch):
    """Image-anchored answers skip generalization; text answers still use it."""
    calls: list[str] = []

    class TrackingAdjuster(StubAdjuster):
        async def generalize(self, answer: str) -> str:
            calls.append(answer)
            return "GENERALIZED — invented specifics"

    memory = RecordingMemory()
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=None,
            adjuster=TrackingAdjuster(), enricher=StubEnricher(), validator=None,
        ),
    )

    openai_compat._bg_generalize_and_store(
        "clean", "The syllabus describes Complex Analysis, course 142180.", "orig", "ws",
        "ns", "default", None, None, "document", "142180 analysis complex",
    )
    assert calls == [], "image answers must not be generalized"
    assert memory.stored[0]["answer"] == "The syllabus describes Complex Analysis, course 142180."
    assert memory.stored[0]["image_kind"] == "document"
    assert memory.stored[0]["image_text"] == "142180 analysis complex"

    # A text answer (no image_kind) still goes through the generalizer.
    openai_compat._bg_generalize_and_store("clean2", "raw text answer", "orig", "ws", "ns")
    assert calls == ["raw text answer"]
    assert memory.stored[1]["answer"] == "GENERALIZED — invented specifics"


def test_bg_store_accepts_all_image_arguments_positionally():
    """The Celery-failure fallback is called positionally; the signature must match."""
    import inspect

    params = list(inspect.signature(openai_compat._bg_generalize_and_store).parameters)
    assert params == [
        "clean_query", "answer", "original_query", "tenant_id", "cache_namespace",
        "model_profile", "image_dhash", "image_clip", "image_kind", "image_text",
        "file_sha", "file_kind", "rag_document_ids", "rag_document_id",
    ]
