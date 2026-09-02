"""The classifier picker: which of legacy (NVIDIA DeBERTa) / LaBSE decides
routing for a workspace, and that each keeps its own threshold. See
app/routers/openai_compat.py's EffectiveLlmConfig.active_routing_threshold
and _classifier_for_choice.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubExternalLLM,
    StubMemory,
    StubNormalizer,
    StubRouter,
)
from tests.test_routing_threshold_default import ScoredClassifier


class PermissiveExternalLLM:
    """Unlike StubExternalLLM (which asserts it's never called), this
    accepts a hard-route call - several tests here route external on
    purpose and only care about the classify decision, not the answer."""

    async def generate_response(self, request, provider=None, api_key=None):
        from app.schemas.chat import ExternalLLMResponse

        return ExternalLLMResponse(
            text="external answer", model_used=request.model, prompt_tokens=5,
            completion_tokens=6, latency_ms=10.0,
        )


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


def _patch_pipeline(monkeypatch, classifier_choice: str, external_llm=None, **extra_config):
    async def _noop_log(*args, **kwargs):
        return None

    from cryptography.fernet import Fernet
    from tests.test_openai_compat_smoke import stored_credential

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_external_llm", external_llm or StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_workspace_provider_key", stored_credential("sk-live"))
    monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    extra_config.setdefault("legacy_routing_threshold", openai_compat.LEGACY_ROUTING_THRESHOLD)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash",
            routing_threshold=openai_compat.ROUTING_THRESHOLD,
            classifier_choice=classifier_choice,
            **extra_config,
        ),
    )


def _ask():
    client = TestClient(app, headers=_AUTH)
    return client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}], "stream": False},
    )


def test_default_classifier_choice_is_labse(monkeypatch):
    """No override -> EffectiveLlmConfig.classifier_choice defaults to
    DEFAULT_CLASSIFIER_CHOICE ("labse") - existing installs keep routing
    exactly as before this feature shipped."""
    assert openai_compat.EffectiveLlmConfig(
        external_model=None, routing_threshold=0.5
    ).classifier_choice == "labse"


def test_labse_active_routes_on_labse_classifier_only(monkeypatch):
    """StubClassifier for legacy would route hard if consulted (score 0.99);
    it must be ignored while labse is the active choice."""
    monkeypatch.setattr(openai_compat, "_labse_classifier", ScoredClassifier(0.20))
    monkeypatch.setattr(openai_compat, "_classifier", ScoredClassifier(0.99))
    _patch_pipeline(monkeypatch, classifier_choice="labse")

    resp = _ask()

    assert resp.status_code == 200
    assert resp.headers["x-dejaq-prompt-difficulty"] == "easy"
    assert resp.headers["x-dejaq-model-used"] == openai_compat.LOCAL_LLM_MODEL_NAME


def test_legacy_active_routes_on_legacy_classifier_only(monkeypatch):
    """Same setup, opposite pick - the labse stub would route easy if
    consulted (score 0.20); it must be ignored while legacy is active. This
    is the live proof that classifier_choice actually changes routing."""
    monkeypatch.setattr(openai_compat, "_labse_classifier", ScoredClassifier(0.20))
    monkeypatch.setattr(openai_compat, "_classifier", ScoredClassifier(0.99))
    _patch_pipeline(monkeypatch, classifier_choice="legacy", external_llm=PermissiveExternalLLM())

    resp = _ask()

    assert resp.status_code == 200
    assert resp.headers["x-dejaq-prompt-difficulty"] == "hard"


def test_legacy_classifier_lazy_loads_only_when_selected(monkeypatch):
    """LOAD_LEGACY_CLASSIFIER stays off by default (see app/config.py) - the
    module-level _classifier singleton must be lazily created on the FIRST
    request that actually selects it, not eagerly at import time."""
    monkeypatch.setattr(openai_compat, "_classifier", None)
    calls = []

    class FakeClassifierService:
        def __init__(self):
            calls.append(1)

        def predict_complexity(self, query):
            return {"complexity": "easy", "score": 0.99, "task_type": "qa"}

    monkeypatch.setattr(openai_compat, "ClassifierService", FakeClassifierService)
    monkeypatch.setattr(openai_compat, "_labse_classifier", ScoredClassifier(0.10))
    _patch_pipeline(
        monkeypatch, classifier_choice="legacy", legacy_routing_threshold=0.5,
        external_llm=PermissiveExternalLLM(),
    )

    assert openai_compat._classifier is None
    resp = _ask()
    assert resp.status_code == 200
    assert len(calls) == 1, "legacy classifier must lazy-load exactly once on first use"
    assert openai_compat._classifier is not None

    _ask()
    assert len(calls) == 1, "a second request must reuse the already-loaded instance"


def test_labse_classifier_lazy_loads_when_load_flag_is_false(monkeypatch):
    """Regression for the missing lazy-load guard: DEJAQ_LOAD_LABSE_CLASSIFIER=false
    left the module-level _labse_classifier at None, and with classifier_choice
    at its default ("labse"), _classifier_for_choice used to return that None
    directly instead of lazy-loading (unlike legacy's _get_legacy_classifier).
    None.predict_complexity(...) raised AttributeError, was swallowed by the
    bare `except Exception` in the classify step, and silently fell back to
    {"complexity": "easy"} - every hard question routed local, forever, with
    only a log line. Asserting the getter is non-None is not enough to catch
    this: the defect is that a hard question silently became easy, so this
    asserts the actual classification and route."""
    monkeypatch.setattr(openai_compat, "_labse_classifier", None)
    calls = []

    class FakeLabseClassifierService:
        def __init__(self):
            calls.append(1)

        def predict_complexity(self, query):
            return {"complexity": "hard", "score": 0.99, "task_type": "qa"}

    monkeypatch.setattr(openai_compat, "LabseClassifierService", FakeLabseClassifierService)
    _patch_pipeline(monkeypatch, classifier_choice="labse", external_llm=PermissiveExternalLLM())

    assert openai_compat._labse_classifier is None
    resp = _ask()

    assert resp.status_code == 200
    assert len(calls) == 1, "labse classifier must lazy-load exactly once on first use"
    assert resp.headers["x-dejaq-prompt-difficulty"] == "hard"
    assert openai_compat._labse_classifier is not None

    _ask()
    assert len(calls) == 1, "a second request must reuse the already-loaded instance"


def test_active_routing_threshold_picks_the_matching_field():
    labse_cfg = openai_compat.EffectiveLlmConfig(
        external_model=None, routing_threshold=0.5, classifier_choice="labse", legacy_routing_threshold=0.9,
    )
    assert labse_cfg.active_routing_threshold == 0.5

    legacy_cfg = openai_compat.EffectiveLlmConfig(
        external_model=None, routing_threshold=0.5, classifier_choice="legacy", legacy_routing_threshold=0.9,
    )
    assert legacy_cfg.active_routing_threshold == 0.9
