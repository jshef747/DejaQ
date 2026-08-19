"""DejaQ was sending a hardcoded temperature=0.7 default to providers that
never asked for one, and Claude Opus 4.7+/Sonnet 5 (plus every gpt-5.x row
per OpenRouter) 400 on any non-default temperature. The failure was invisible
because ExternalLLMError was swallowed into a generic HTTP 200 apology - so a
misconfigured workspace also looked like it simply had a cache that never
fills.

This file locks down the fix at the router level:
  * no client temperature -> nothing is sent to the provider client;
  * an explicit client temperature -> still forwarded;
  * a provider 400/429 -> that same status, and a rejected provider credential
    -> 502 (not 401, which on this endpoint means the CALLER's DejaQ key was
    rejected), each carrying a fixed message rather than the provider's own
    text, which can echo a masked form of the workspace's provider key.
"""
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.schemas.chat import ExternalLLMResponse
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubEnricher,
    StubMemory,
    StubNormalizer,
    stored_credential,
)

pytestmark = pytest.mark.no_model


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class _ExplodingClassifier:
    """X-DejaQ-Routing-Mode: hard_external must skip the classifier entirely."""

    def predict_complexity(self, query: str) -> dict:
        raise AssertionError("classifier should be skipped")


class CapturingExternalLLM:
    def __init__(self):
        self.request = None

    async def generate_response(self, request, provider=None, api_key=None):
        self.request = request
        return ExternalLLMResponse(
            text="external answer",
            model_used=request.model,
            prompt_tokens=5,
            completion_tokens=6,
            latency_ms=10.0,
        )


class FailingExternalLLM:
    def __init__(self, exc: Exception):
        self._exc = exc

    async def generate_response(self, request, provider=None, api_key=None):
        raise self._exc


def _setup_hard_route(monkeypatch, external, model="claude-sonnet-5"):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", _ExplodingClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", external)
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model=model,
            routing_threshold=0.75,
        ),
    )
    monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(
        openai_compat, "get_workspace_provider_key", stored_credential("sk-ant-live", providers=("anthropic",))
    )


def _ask_hard_question(temperature=None):
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Explain a hard thing."}],
        "stream": False,
    }
    if temperature is not None:
        body["temperature"] = temperature
    return TestClient(app, headers=_AUTH).post(
        "/v1/chat/completions",
        headers={"X-DejaQ-Routing-Mode": "hard_external"},
        json=body,
    )


def test_no_client_temperature_sends_none_to_the_provider(monkeypatch):
    external = CapturingExternalLLM()
    _setup_hard_route(monkeypatch, external)

    resp = _ask_hard_question(temperature=None)

    assert resp.status_code == 200
    assert external.request.temperature is None


def test_explicit_client_temperature_is_still_forwarded(monkeypatch):
    external = CapturingExternalLLM()
    _setup_hard_route(monkeypatch, external)

    resp = _ask_hard_question(temperature=0.3)

    assert resp.status_code == 200
    assert external.request.temperature == 0.3


def test_provider_400_surfaces_as_a_distinguishable_status_not_the_apology(monkeypatch):
    external = FailingExternalLLM(ExternalLLMError("temperature is deprecated for this model", status_code=400))
    _setup_hard_route(monkeypatch, external)

    resp = _ask_hard_question()

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "anthropic request was rejected" in detail
    assert "temperature is deprecated" not in detail


def test_provider_auth_error_surfaces_as_502_not_401(monkeypatch):
    """401 on this endpoint already means the caller's own DejaQ API key was
    rejected; a rejected PROVIDER credential is an upstream failure (502)."""
    external = FailingExternalLLM(ExternalLLMAuthError("invalid api key: sk-ant-li****ive", status_code=401))
    _setup_hard_route(monkeypatch, external)

    resp = _ask_hard_question()

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "anthropic credential configured for this workspace was rejected" in detail
    assert "sk-ant-li" not in detail


def test_provider_429_surfaces_as_a_distinguishable_status(monkeypatch):
    external = FailingExternalLLM(ExternalLLMError("rate limited", status_code=429))
    _setup_hard_route(monkeypatch, external)

    resp = _ask_hard_question()

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert "anthropic account for this workspace is rate limited" in detail


def test_transient_provider_failure_still_gets_the_generic_apology(monkeypatch):
    """No status_code (a connection error, not an HTTP response) - today's
    code cannot tell that apart from a permanent misconfiguration, and this
    is the one case that should still fall back to the apology at 200."""
    external = FailingExternalLLM(ExternalLLMError("connection reset"))
    _setup_hard_route(monkeypatch, external)

    resp = _ask_hard_question()

    assert resp.status_code == 200
    assert "couldn't process your request" in resp.json()["choices"][0]["message"]["content"]
