import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import ollama_catalog

pytestmark = pytest.mark.no_model


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


def _stub_post(monkeypatch, responses):
    """responses: list of (status_code, json_body) consumed in call order."""
    calls: list[tuple[str, dict]] = []

    def _fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        status, body = responses[len(calls) - 1]
        request = httpx.Request("POST", url)
        return httpx.Response(status, json=body, request=request)

    monkeypatch.setattr(httpx, "post", _fake_post)
    return calls


@pytest.fixture(autouse=True)
def _reset_catalog_cache():
    """The module-level caches are process-lifetime - reset them around
    every test so one test's fetch doesn't leak into the next."""
    ollama_catalog._CACHE = ollama_catalog._CatalogCache(ttl_seconds=ollama_catalog._CACHE._ttl)
    ollama_catalog._CAPABILITY_CACHE = ollama_catalog._CapabilityCache(
        ttl_seconds=ollama_catalog._CAPABILITY_CACHE._ttl
    )
    yield
    ollama_catalog._CACHE = ollama_catalog._CatalogCache(ttl_seconds=ollama_catalog._CACHE._ttl)
    ollama_catalog._CAPABILITY_CACHE = ollama_catalog._CapabilityCache(
        ttl_seconds=ollama_catalog._CAPABILITY_CACHE._ttl
    )


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


# ── supports_vision (/api/show, deliberately not /api/tags) ──


def test_supports_vision_true_when_capabilities_include_vision(monkeypatch):
    calls = _stub_post(monkeypatch, [(200, {"capabilities": ["completion", "vision", "tools"]})])

    assert ollama_catalog.supports_vision("gemma4:e4b") is True
    assert calls == [(f"{ollama_catalog.OLLAMA_URL}/api/show", {"model": "gemma4:e4b"})]


def test_supports_vision_false_when_capabilities_omit_vision(monkeypatch):
    _stub_post(monkeypatch, [(200, {"capabilities": ["completion", "tools"]})])

    assert ollama_catalog.supports_vision("qwen2.5:1.5b") is False


def test_supports_vision_caches_within_ttl(monkeypatch):
    calls = _stub_post(monkeypatch, [(200, {"capabilities": ["completion", "vision"]})] * 3)

    ollama_catalog.supports_vision("gemma4:e4b")
    ollama_catalog.supports_vision("gemma4:e4b")
    ollama_catalog.supports_vision("gemma4:e4b")

    assert len(calls) == 1


def test_supports_vision_caches_independently_per_model(monkeypatch):
    calls = _stub_post(monkeypatch, [
        (200, {"capabilities": ["completion", "vision"]}),
        (200, {"capabilities": ["completion"]}),
    ])

    assert ollama_catalog.supports_vision("gemma4:e4b") is True
    assert ollama_catalog.supports_vision("qwen2.5:1.5b") is False
    assert len(calls) == 2


def test_supports_vision_degrades_to_none_when_ollama_unreachable(monkeypatch):
    """A read-only indicator - unreachable Ollama must never raise or block."""
    def _fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _fake_post)

    assert ollama_catalog.supports_vision("gemma4:e4b") is None


def test_supports_vision_degrades_to_none_when_model_not_found(monkeypatch):
    """/api/show 404s for a model that isn't installed - also just 'unknown'."""
    _stub_post(monkeypatch, [(404, {"error": "model not found"})])

    assert ollama_catalog.supports_vision("does-not-exist:latest") is None


def test_supports_vision_force_refresh_bypasses_the_cache(monkeypatch):
    calls = _stub_post(monkeypatch, [
        (200, {"capabilities": ["completion", "vision"]}),
        (200, {"capabilities": ["completion"]}),
    ])

    first = ollama_catalog.supports_vision("gemma4:e4b")
    second = ollama_catalog.supports_vision("gemma4:e4b", force_refresh=True)

    assert len(calls) == 2
    assert first is True
    assert second is False
