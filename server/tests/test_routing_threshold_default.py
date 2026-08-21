"""Routing at the DEJAQ_ROUTING_THRESHOLD default (0.2986, paired with the
re-derived classifier weights - see app/config.py). Verifies the
auto-routing decision on each side of the line when the workspace has no
override, mirroring the existing test_auto_routing_uses_org_threshold_zero_to_route_external
pattern.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.schemas.chat import ExternalLLMResponse
from tests.conftest import StreamingLocalRouterMixin
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubEnricher,
    StubExternalLLM,
    StubMemory,
    StubNormalizer,
)


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class ScoredClassifier:
    def __init__(self, score: float):
        self.score = score

    def predict_complexity(self, query: str) -> dict:
        return {"complexity": "easy", "score": self.score, "task_type": "qa"}


class StubRouter(StreamingLocalRouterMixin):
    async def generate_local_response(self, query: str, history=None, max_tokens=1024, system_prompt=None):
        return "local answer", 12.0, "stop"


def test_default_routing_threshold_is_0_2986():
    assert openai_compat.ROUTING_THRESHOLD == 0.2986


def _default_llm_config(monkeypatch):
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash",
            routing_threshold=openai_compat.ROUTING_THRESHOLD,
        ),
    )


def test_score_just_below_default_threshold_routes_local(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    from tests.test_openai_compat_smoke import StubAdjuster

    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", ScoredClassifier(0.25))
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    _default_llm_config(monkeypatch)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-dejaq-prompt-difficulty"] == "easy"
    assert response.headers["x-dejaq-model-used"] == openai_compat.LOCAL_LLM_MODEL_NAME


def test_score_at_or_above_default_threshold_routes_external(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    class CapturingExternalLLM:
        async def generate_response(self, request, provider=None, api_key=None):
            return ExternalLLMResponse(
                text="external answer",
                model_used=request.model,
                prompt_tokens=5,
                completion_tokens=6,
                latency_ms=10.0,
            )

    from cryptography.fernet import Fernet

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", ScoredClassifier(0.30))
    monkeypatch.setattr(openai_compat, "_external_llm", CapturingExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _default_llm_config(monkeypatch)

    from tests.test_openai_compat_smoke import stored_credential

    monkeypatch.setattr(openai_compat, "get_workspace_provider_key", stored_credential("sk-live"))

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Explain something hard."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-dejaq-prompt-difficulty"] == "hard"
    assert response.json()["choices"][0]["message"]["content"] == "external answer"
