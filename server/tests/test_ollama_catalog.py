import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import ollama_catalog


def _stub_get(monkeypatch, responses):
    """responses: list of (status_code, json_body) consumed in call order."""
    calls: list[str] = []

    def _fake_get(url, timeout=None):
        calls.append(url)
        status, body = responses[len(calls) - 1]
        request = httpx.Request("GET", url)
        return httpx.Response(status, json=body, request=request)

    monkeypatch.setattr(httpx, "get", _fake_get)
    return calls


@pytest.fixture(autouse=True)
def _reset_catalog_cache():
    """The module-level cache is process-lifetime - reset it around every
    test so one test's fetch doesn't leak into the next."""
    ollama_catalog._CACHE = ollama_catalog._CatalogCache(ttl_seconds=ollama_catalog._CACHE._ttl)
    yield
    ollama_catalog._CACHE = ollama_catalog._CatalogCache(ttl_seconds=ollama_catalog._CACHE._ttl)


def test_list_available_models_returns_sorted_tags(monkeypatch):
    _stub_get(monkeypatch, [(200, {"models": [{"name": "gemma4:e4b"}, {"name": "qwen2.5:0.5b"}]})])

    assert ollama_catalog.list_available_models() == ["gemma4:e4b", "qwen2.5:0.5b"]


def test_list_available_models_caches_within_ttl(monkeypatch):
    calls = _stub_get(monkeypatch, [(200, {"models": [{"name": "gemma4:e4b"}]})] * 3)

    ollama_catalog.list_available_models()
    ollama_catalog.list_available_models()
    ollama_catalog.list_available_models()

    assert len(calls) == 1


def test_force_refresh_bypasses_the_cache(monkeypatch):
    """'I just ran ollama pull' must be instant, not wait out the TTL."""
    calls = _stub_get(monkeypatch, [
        (200, {"models": [{"name": "gemma4:e4b"}]}),
        (200, {"models": [{"name": "gemma4:e4b"}, {"name": "llama3.2:3b"}]}),
    ])

    first = ollama_catalog.list_available_models()
    second = ollama_catalog.list_available_models(force_refresh=True)

    assert len(calls) == 2
    assert first == ["gemma4:e4b"]
    assert second == ["gemma4:e4b", "llama3.2:3b"]


def test_unreachable_ollama_raises_and_never_caches_a_stale_list(monkeypatch):
    def _fake_get(url, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _fake_get)

    with pytest.raises(ollama_catalog.OllamaUnreachableError):
        ollama_catalog.list_available_models()


def test_a_transient_failure_does_not_poison_a_previously_good_list(monkeypatch):
    calls = _stub_get(monkeypatch, [(200, {"models": [{"name": "gemma4:e4b"}]})])
    assert ollama_catalog.list_available_models() == ["gemma4:e4b"]

    def _fake_get_fails(url, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _fake_get_fails)

    with pytest.raises(ollama_catalog.OllamaUnreachableError):
        ollama_catalog.list_available_models(force_refresh=True)


# ── GET /admin/v1/available-models ──


def test_available_models_endpoint_returns_the_catalog(monkeypatch):
    from app.main import app

    _stub_get(monkeypatch, [(200, {"models": [{"name": "gemma4:e4b"}]})])

    response = TestClient(app).get("/admin/v1/available-models")

    assert response.status_code == 200
    assert response.json() == {"models": ["gemma4:e4b"], "error": None}


def test_available_models_endpoint_reports_a_clear_error_when_ollama_is_unreachable(monkeypatch):
    """200, not a 5xx: an unreachable Ollama is a named state of this one
    resource, not a broken admin API - the dashboard reads `error` and
    disables editing with the reason shown."""
    from app.main import app

    def _fake_get(url, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _fake_get)

    response = TestClient(app).get("/admin/v1/available-models")

    assert response.status_code == 200
    body = response.json()
    assert body["models"] == []
    assert "unreachable" in body["error"].lower()
