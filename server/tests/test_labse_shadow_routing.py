"""Hebrew no longer gets a dedicated routing judge - it falls through to the
same classify step (and shadow log) as every other language. The LaBSE
shadow classifier computes and logs a decision on that same step but must
never affect the served route, even when it disagrees with the production
classifier, and a shadow failure must never break the request.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from tests.test_openai_compat_smoke import (
    _AUTH,
    HardClassifier,
    StubAdjuster,
    StubClassifier,
    StubEnricher,
    StubExternalLLM,
    StubMemory,
    StubNormalizer,
    StubRouter,
)


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class ScoredClassifier:
    def __init__(self, complexity: str, score: float):
        self.complexity = complexity
        self.score = score

    def predict_complexity(self, query: str) -> dict:
        return {"complexity": self.complexity, "score": self.score, "task_type": "qa"}


class SpyShadowClassifier:
    def __init__(self, complexity: str, score: float):
        self.complexity = complexity
        self.score = score
        self.calls = 0

    def predict_complexity(self, query: str) -> dict:
        self.calls += 1
        return {"complexity": self.complexity, "score": self.score, "task_type": "labse_shadow"}


class ExplodingShadowClassifier:
    def predict_complexity(self, query: str) -> dict:
        raise RuntimeError("shadow backend unavailable")


def _wire_common(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash",
            routing_threshold=openai_compat.ROUTING_THRESHOLD,
        ),
    )


def _post(query: str):
    client = TestClient(app, headers=_AUTH)
    return client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": query}],
            "stream": False,
        },
    )


def test_hebrew_easy_query_routes_local_like_any_other_language(monkeypatch):
    """No Hebrew-specific branch remains: a Hebrew query with an easy-scored
    classifier routes local exactly like an English one would."""
    _wire_common(monkeypatch)
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_labse_classifier", None)

    response = _post("מה בירת צרפת?")

    assert response.status_code == 200
    assert response.headers["x-dejaq-prompt-difficulty"] == "easy"
    assert response.headers["x-dejaq-model-used"] == openai_compat.LOCAL_LLM_MODEL_NAME


def test_hebrew_hard_query_routes_external_like_any_other_language(monkeypatch):
    """Same classify path decides Hebrew's routing as every other language -
    no dedicated judge intercepts it first."""
    _wire_common(monkeypatch)
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "_labse_classifier", None)

    from cryptography.fernet import Fernet

    from app.schemas.chat import ExternalLLMResponse

    class CapturingExternalLLM:
        async def generate_response(self, request, provider=None, api_key=None):
            return ExternalLLMResponse(
                text="external answer", model_used=request.model,
                prompt_tokens=5, completion_tokens=6, latency_ms=10.0,
            )

    monkeypatch.setattr(openai_compat, "_external_llm", CapturingExternalLLM())
    monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())

    from tests.test_openai_compat_smoke import stored_credential

    monkeypatch.setattr(openai_compat, "get_workspace_provider_key", stored_credential("sk-live"))

    response = _post("הוכח שיש אינסוף מספרים ראשוניים.")

    assert response.status_code == 200
    assert response.headers["x-dejaq-prompt-difficulty"] == "hard"


def test_shadow_classifier_runs_but_never_changes_the_route(monkeypatch):
    """Shadow disagrees (says hard) with the production classifier (easy) -
    the served route must still follow the production classifier."""
    _wire_common(monkeypatch)
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    shadow = SpyShadowClassifier("hard", 0.99)
    monkeypatch.setattr(openai_compat, "_labse_classifier", shadow)

    response = _post("What is the capital of France?")

    assert response.status_code == 200
    assert response.headers["x-dejaq-prompt-difficulty"] == "easy"
    assert response.headers["x-dejaq-model-used"] == openai_compat.LOCAL_LLM_MODEL_NAME
    assert shadow.calls == 1


def test_shadow_classifier_failure_does_not_break_the_request(monkeypatch):
    _wire_common(monkeypatch)
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_labse_classifier", ExplodingShadowClassifier())

    response = _post("What is the capital of France?")

    assert response.status_code == 200
    assert response.headers["x-dejaq-prompt-difficulty"] == "easy"
