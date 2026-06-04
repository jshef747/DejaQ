import asyncio
import hashlib
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.no_model


@pytest.fixture(autouse=True)
def _credential_key(monkeypatch):
    """Provide a valid Fernet key so CredentialService() can be constructed
    without depending on a populated server/.env."""
    from cryptography.fernet import Fernet
    import app.config as config

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("DEJAQ_CREDENTIAL_ENCRYPTION_KEY", key)
    monkeypatch.setattr(config, "CREDENTIAL_ENCRYPTION_KEY", key, raising=False)


def _interaction(served_tier: str):
    from app.services.response_registry import ResponseInteraction

    return ResponseInteraction(
        interaction_id="int_parent",
        workspace_id=7,
        workspace_slug="acme",
        department="eng",
        cache_namespace="acme__eng",
        served_tier=served_tier,
        response_id=None,
        message_hash="hash",
        created_at="2026-01-01T00:00:00+00:00",
        escalation_attempted=False,
        escalation_attempted_at=None,
    )


def test_cache_tier_escalates_to_local_llm(monkeypatch):
    from app.services import escalation
    from app.services.response_registry import ResponseInteraction

    class Router:
        async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
            self.query = query
            self.history = history
            self.system_prompt = system_prompt
            return "local better answer", 11.0

    class Registry:
        async def register(self, **kwargs):
            self.kwargs = kwargs
            return ResponseInteraction(
                interaction_id="int_child",
                workspace_id=kwargs["workspace_id"],
                workspace_slug=kwargs["workspace_slug"],
                department=kwargs["department"],
                cache_namespace=kwargs["cache_namespace"],
                served_tier=kwargs["served_tier"],
                response_id=kwargs["response_id"],
                message_hash="hash",
                created_at="2026-01-01T00:00:01+00:00",
                escalation_attempted=False,
                escalation_attempted_at=None,
            )

    class Logger:
        def __init__(self):
            self.calls = []

        async def log(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    router = Router()
    registry = Registry()
    logger = Logger()

    async def _cache_response_id_for_escalation(**kwargs):
        return "acme__eng:localdoc"

    monkeypatch.setattr(escalation, "get_llm_router_service", lambda: router)
    monkeypatch.setattr(escalation, "response_registry", registry)
    monkeypatch.setattr(escalation, "request_logger", logger)
    monkeypatch.setattr(escalation, "_cache_response_id_for_escalation", _cache_response_id_for_escalation)

    result = asyncio.run(
        escalation.escalate(
            interaction=_interaction("cache"),
            messages=[
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Old question"},
                {"role": "assistant", "content": "Old answer"},
                {"role": "user", "content": "Current question"},
            ],
        )
    )

    assert result.escalation_status == "answered"
    assert result.escalated_response is not None
    assert result.escalated_response.content == "local better answer"
    assert result.escalated_response.tier == "local"
    assert result.escalated_response.interaction_id == "int_child"
    assert result.escalated_response.response_id == "acme__eng:localdoc"
    assert router.query == "Current question"
    assert router.history == [
        {"role": "user", "content": "Old question"},
        {"role": "assistant", "content": "Old answer"},
    ]
    assert router.system_prompt == "Be concise."
    assert logger.calls
    _, kwargs = logger.calls[0]
    assert kwargs["source"] == "feedback_escalation"
    assert kwargs["interaction_id"] == "int_child"
    assert kwargs["parent_interaction_id"] == "int_parent"
    assert kwargs["served_tier"] == "local"
    assert registry.kwargs["response_id"] == "acme__eng:localdoc"


def test_escalation_log_failure_does_not_fail_answer(monkeypatch):
    from app.services import escalation
    from app.services.response_registry import ResponseInteraction

    class Router:
        async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
            return "local better answer", 11.0

    class Registry:
        async def register(self, **kwargs):
            return ResponseInteraction(
                interaction_id="int_child",
                workspace_id=kwargs["workspace_id"],
                workspace_slug=kwargs["workspace_slug"],
                department=kwargs["department"],
                cache_namespace=kwargs["cache_namespace"],
                served_tier=kwargs["served_tier"],
                response_id=kwargs["response_id"],
                message_hash="hash",
                created_at="2026-01-01T00:00:01+00:00",
                escalation_attempted=False,
                escalation_attempted_at=None,
            )

    class FailingLogger:
        async def log(self, *args, **kwargs):
            raise RuntimeError("disk full")

    monkeypatch.setattr(escalation, "get_llm_router_service", lambda: Router())
    monkeypatch.setattr(escalation, "response_registry", Registry())
    monkeypatch.setattr(escalation, "request_logger", FailingLogger())

    async def _cache_response_id_for_escalation(**kwargs):
        return None

    monkeypatch.setattr(escalation, "_cache_response_id_for_escalation", _cache_response_id_for_escalation)

    result = asyncio.run(
        escalation.escalate(
            interaction=_interaction("cache"),
            messages=[{"role": "user", "content": "Hello"}],
        )
    )

    assert result.escalation_status == "answered"


def test_external_tier_returns_no_further_escalation():
    from app.services import escalation

    result = asyncio.run(
        escalation.escalate(
            interaction=_interaction("external"),
            messages=[{"role": "user", "content": "Hello"}],
        )
    )

    assert result.escalation_status == "no_further_escalation"
    assert result.escalated_response is None


def test_local_tier_without_credential_returns_no_credential(monkeypatch):
    from app.services import escalation

    monkeypatch.setattr(
        escalation.llm_config_service,
        "read_for_workspace",
        lambda workspace_slug: type("Cfg", (), {"external_model": "gpt-5.4-mini"})(),
    )
    monkeypatch.setattr(escalation, "provider_for_model", lambda model: "openai")
    monkeypatch.setattr(
        escalation.CredentialService,
        "get_decrypted_key",
        lambda self, session, workspace_id, provider: None,
    )

    result = asyncio.run(
        escalation.escalate(
            interaction=_interaction("local"),
            messages=[{"role": "user", "content": "Hello"}],
        )
    )

    assert result.escalation_status == "no_credential"
    assert result.escalated_response is None


def test_local_tier_escalates_to_external_llm(monkeypatch):
    from app.schemas.chat import ExternalLLMResponse
    from app.services import escalation
    from app.services.response_registry import ResponseInteraction

    class Registry:
        async def register(self, **kwargs):
            return ResponseInteraction(
                interaction_id="int_external_child",
                workspace_id=kwargs["workspace_id"],
                workspace_slug=kwargs["workspace_slug"],
                department=kwargs["department"],
                cache_namespace=kwargs["cache_namespace"],
                served_tier=kwargs["served_tier"],
                response_id=kwargs["response_id"],
                message_hash="hash",
                created_at="2026-01-01T00:00:01+00:00",
                escalation_attempted=False,
                escalation_attempted_at=None,
            )

    class External:
        async def generate_response(self, request, provider, api_key):
            self.request = request
            self.provider = provider
            self.api_key = api_key
            return ExternalLLMResponse(
                text="external better answer",
                model_used=request.model,
                prompt_tokens=1,
                completion_tokens=2,
                latency_ms=3,
            )

    @contextmanager
    def fake_session():
        yield object()

    external = External()

    async def _cache_response_id_for_escalation(**kwargs):
        return "acme__eng:externaldoc"

    monkeypatch.setattr(escalation, "response_registry", Registry())
    monkeypatch.setattr(escalation, "_cache_response_id_for_escalation", _cache_response_id_for_escalation)
    monkeypatch.setattr(
        escalation.llm_config_service,
        "read_for_workspace",
        lambda workspace_slug: type("Cfg", (), {"external_model": "gpt-5.4-mini"})(),
    )
    monkeypatch.setattr(escalation, "provider_for_model", lambda model: "openai")
    monkeypatch.setattr(escalation, "get_session", fake_session)
    monkeypatch.setattr(
        escalation.CredentialService,
        "get_decrypted_key",
        lambda self, session, workspace_id, provider: "sk-test",
    )
    monkeypatch.setattr(escalation, "ExternalLLMService", lambda: external)

    result = asyncio.run(
        escalation.escalate(
            interaction=_interaction("local"),
            messages=[{"role": "user", "content": "Hello"}],
        )
    )

    assert result.escalation_status == "answered"
    assert result.escalated_response is not None
    assert result.escalated_response.content == "external better answer"
    assert result.escalated_response.tier == "external"
    assert result.escalated_response.interaction_id == "int_external_child"
    assert result.escalated_response.response_id == "acme__eng:externaldoc"
    assert external.request.query == "Hello"
    assert external.provider == "openai"
    assert external.api_key == "sk-test"


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        ("timeout", "timeout"),
        ("provider", "provider_error"),
    ],
)
def test_local_tier_external_failures_return_status(monkeypatch, raised, expected):
    from app.services import escalation
    from app.utils.exceptions import ExternalLLMError, ExternalLLMTimeoutError

    class External:
        async def generate_response(self, request, provider, api_key):
            if raised == "timeout":
                raise ExternalLLMTimeoutError("slow")
            raise ExternalLLMError("boom")

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(
        escalation.llm_config_service,
        "read_for_workspace",
        lambda workspace_slug: type("Cfg", (), {"external_model": "gpt-5.4-mini"})(),
    )
    monkeypatch.setattr(escalation, "provider_for_model", lambda model: "openai")
    monkeypatch.setattr(escalation, "get_session", fake_session)
    monkeypatch.setattr(
        escalation.CredentialService,
        "get_decrypted_key",
        lambda self, session, workspace_id, provider: "sk-test",
    )
    monkeypatch.setattr(escalation, "ExternalLLMService", lambda: External())

    result = asyncio.run(
        escalation.escalate(
            interaction=_interaction("local"),
            messages=[{"role": "user", "content": "Hello"}],
        )
    )

    assert result.escalation_status == expected
    assert result.escalated_response is None


def test_cache_helper_returns_response_id_and_schedules_store_when_cacheable(monkeypatch):
    from app.services import escalation

    class Enricher:
        async def enrich(self, query, history):
            self.query = query
            self.history = history
            return "enriched current question"

    class Normalizer:
        async def normalize(self, enriched):
            self.enriched = enriched
            return "normalized current question"

    scheduled = []
    enricher = Enricher()
    normalizer = Normalizer()

    monkeypatch.setattr(escalation, "get_context_enricher_service", lambda: enricher)
    monkeypatch.setattr(escalation, "get_normalizer_service", lambda: normalizer)
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean: (True, "passed"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("cache"),
            query="Current question",
            history=[{"role": "user", "content": "Old question"}],
            answer="better answer",
        )
    )

    expected_doc_id = hashlib.sha256("normalized current question".encode()).hexdigest()[:16]
    assert response_id == f"acme__eng:{expected_doc_id}"
    assert enricher.query == "Current question"
    assert enricher.history == [{"role": "user", "content": "Old question"}]
    assert normalizer.enriched == "enriched current question"
    assert scheduled == [
        {
            "clean_query": "normalized current question",
            "answer": "better answer",
            "original_query": "Current question",
            "tenant_id": "acme",
            "cache_namespace": "acme__eng",
        }
    ]


def test_cache_helper_returns_none_when_not_cacheable(monkeypatch):
    from app.services import escalation

    class Enricher:
        async def enrich(self, query, history):
            return query

    class Normalizer:
        async def normalize(self, enriched):
            return "hi"

    scheduled = []
    monkeypatch.setattr(escalation, "get_context_enricher_service", lambda: Enricher())
    monkeypatch.setattr(escalation, "get_normalizer_service", lambda: Normalizer())
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean: (False, "query too short"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("cache"),
            query="Hi",
            history=[],
            answer="hello",
        )
    )

    assert response_id is None
    assert scheduled == []
