"""Stage 1f: the server no longer bakes in a default external model.

`EXTERNAL_MODEL_NAME` is `None` unless `DEJAQ_EXTERNAL_MODEL` is set - no more
silent fall-through to `gemini-2.5-flash`. A hard query with no workspace
override and no env default must fail with a clear, actionable error instead
of being routed to a model nobody chose. Cache hits and the local model must
stay completely unaffected, since complexity routing decides "external" is
even needed before EXTERNAL_MODEL_NAME is ever read.
"""
import importlib

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
    StubHitMemory,
    StubMemory,
    StubNormalizer,
    StubRouter,
)

pytestmark = pytest.mark.no_model


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


def test_env_var_absent_means_no_baked_in_default(monkeypatch):
    """The actual mechanism: config.py must not substitute a literal model."""
    import app.config as config

    monkeypatch.delenv("DEJAQ_EXTERNAL_MODEL", raising=False)
    importlib.reload(config)
    try:
        assert config.EXTERNAL_MODEL_NAME is None
    finally:
        # undo() BEFORE the reload: monkeypatch's own teardown runs after this
        # block, so reloading first would re-read the patched environment and
        # leave the module constant wrong for every later test in the session.
        monkeypatch.undo()
        importlib.reload(config)


def test_env_var_set_is_still_an_honored_deployment_default(monkeypatch):
    """An explicitly set DEJAQ_EXTERNAL_MODEL remains a legitimate default."""
    import app.config as config

    monkeypatch.setenv("DEJAQ_EXTERNAL_MODEL", "gemini-2.5-flash")
    importlib.reload(config)
    try:
        assert config.EXTERNAL_MODEL_NAME == "gemini-2.5-flash"
    finally:
        # See the note above: without undo() first, this reload pins
        # EXTERNAL_MODEL_NAME to "gemini-2.5-flash" for the rest of the run and
        # test_llm_config_service's default-model assertions fail by ordering.
        monkeypatch.undo()
        importlib.reload(config)


def test_unconfigured_workspace_hard_query_gets_actionable_error(monkeypatch):
    async def _log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "EXTERNAL_MODEL_NAME", None)
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Prove that there are infinitely many prime numbers."}],
            "stream": False,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "No external model configured" in detail
    assert "Settings" in detail


def test_configured_workspace_hard_query_unaffected(monkeypatch):
    async def _log(*a, **k):
        return None

    from app.schemas.chat import ExternalLLMResponse

    class OkExternalLLM:
        async def generate_response(self, request, provider=None, api_key=None):
            return ExternalLLMResponse(
                text="Paris is the capital of France.",
                model_used="gemini-2.5-flash",
                finish_reason="stop",
            )

    monkeypatch.setattr(openai_compat, "EXTERNAL_MODEL_NAME", "gemini-2.5-flash")
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", OkExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _log)
    monkeypatch.setattr(
        openai_compat, "get_workspace_provider_key",
        lambda session, workspace_id, provider: "decrypted-key",
    )
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Prove that there are infinitely many prime numbers."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert "Paris" in response.json()["choices"][0]["message"]["content"]


def test_local_model_path_unaffected_by_unconfigured_external_model(monkeypatch):
    async def _log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "EXTERNAL_MODEL_NAME", None)
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

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
    assert "Paris" in response.json()["choices"][0]["message"]["content"]


def test_cache_hit_unaffected_by_unconfigured_external_model(monkeypatch):
    async def _log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "EXTERNAL_MODEL_NAME", None)
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _log)

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
    assert response.json()["choices"][0]["message"]["content"] == "Cached Paris answer."
