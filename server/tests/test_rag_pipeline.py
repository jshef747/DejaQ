"""RAG pipeline integration: retrieval grounds generation on a cache miss.

Reuses the same stubbing style as test_openai_compat_smoke. The retrieval call is
mocked to return (or not return) chunks; a capturing local router records the query
the model actually receives, so we can assert the knowledge was injected — and that
it was NOT when nothing was retrieved, and never enters the cache key.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.memory_chromaDB import CacheLookupResult
from tests.conftest import StreamingLocalRouterMixin

pytestmark = pytest.mark.no_model

_AUTH = {"Authorization": "Bearer test-key"}


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class StubEnricher:
    async def enrich(self, message, history):
        return message


class StubNormalizer:
    async def normalize(self, raw_query):
        return raw_query.lower()


class StubAdjuster:
    async def generalize(self, answer):
        return answer

    async def adjust(self, original_query, general_answer):
        return general_answer


class StubClassifier:
    def predict_complexity(self, query):
        return {"complexity": "easy", "score": 0.0, "task_type": "qa"}


class StubMemory:
    def lookup_cache(self, clean_query):
        return CacheLookupResult(hit=False)

    def check_cache(self, clean_query):
        return None


class CapturingRouter(StreamingLocalRouterMixin):
    def __init__(self):
        self.query = None

    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
        self.query = query
        return "grounded answer", 10.0, "stop"


class _Chunk:
    def __init__(self, text, title="KB", distance=0.2):
        self.text = text
        self.title = title
        self.distance = distance
        self.rag_document_id = 1
        self.chunk_index = 0


def _common_stubs(monkeypatch, router, store_captured=None):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    def _should_cache(enriched, clean, **kw):
        if store_captured is not None:
            store_captured["clean"] = clean
        return (False, "test")

    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", _should_cache)


def test_retrieved_knowledge_is_injected_into_the_prompt(monkeypatch):
    router = CapturingRouter()
    _common_stubs(monkeypatch, router)
    monkeypatch.setattr(
        openai_compat.rag_service, "retrieve",
        lambda ns, q, k, d: [_Chunk("The office WiFi password is hunter2.")],
    )

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the WiFi password?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert "WORKSPACE KNOWLEDGE" in router.query
    assert "hunter2" in router.query
    assert "Question: What is the WiFi password?" in router.query
    assert response.headers.get("x-dejaq-rag-chunks") == "1"


def test_no_retrieved_knowledge_leaves_the_prompt_untouched(monkeypatch):
    router = CapturingRouter()
    _common_stubs(monkeypatch, router)
    monkeypatch.setattr(openai_compat.rag_service, "retrieve", lambda ns, q, k, d: [])

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the WiFi password?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert router.query == "What is the WiFi password?"  # unchanged
    assert "x-dejaq-rag-chunks" not in response.headers


def test_rag_context_never_enters_the_cache_key(monkeypatch):
    router = CapturingRouter()
    captured: dict = {}
    _common_stubs(monkeypatch, router, store_captured=captured)
    monkeypatch.setattr(
        openai_compat.rag_service, "retrieve",
        lambda ns, q, k, d: [_Chunk("Sensitive internal knowledge.")],
    )

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the WiFi password?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    # The cache key (normalized query) is the bare question, not the injected text.
    assert captured["clean"] == "what is the wifi password?"
    assert "Sensitive internal knowledge" not in captured["clean"]


def test_rag_disabled_skips_retrieval(monkeypatch):
    router = CapturingRouter()
    _common_stubs(monkeypatch, router)
    monkeypatch.setattr(openai_compat, "RAG_ENABLED", False)

    def _boom(*a, **k):
        raise AssertionError("retrieve must not be called when RAG is disabled")

    monkeypatch.setattr(openai_compat.rag_service, "retrieve", _boom)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        },
    )
    assert response.status_code == 200
    assert router.query == "hello"
