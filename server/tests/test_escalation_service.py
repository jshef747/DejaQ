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


def _interaction(served_tier: str, response_id: str | None = None):
    from app.services.response_registry import ResponseInteraction

    return ResponseInteraction(
        interaction_id="int_parent",
        workspace_id=7,
        workspace_slug="acme",
        department="eng",
        cache_namespace="acme__eng",
        served_tier=served_tier,
        response_id=response_id,
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
            return "local better answer", 11.0, "stop"

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
            return "local better answer", 11.0, "stop"

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


class _RecordingRegistry:
    async def register(self, **kwargs):
        from app.services.response_registry import ResponseInteraction

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


def _patch_cacheable_pipeline(monkeypatch, escalation, scheduled):
    """Wire the real _cache_response_id_for_escalation up to a cacheable query,
    so a test can tell a skipped store from a scheduled one."""

    class Enricher:
        async def enrich(self, query, history):
            return query

    class Normalizer:
        async def normalize(self, enriched):
            return "normalized current question"

    monkeypatch.setattr(escalation, "get_context_enricher_service", lambda: Enricher())
    monkeypatch.setattr(escalation, "get_normalizer_service", lambda: Normalizer())
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "passed"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))


def test_truncated_local_escalation_is_answered_but_not_cached(monkeypatch):
    from app.services import escalation

    class Router:
        async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
            return "The capital of Fra", 11.0, "length"

    scheduled = []
    registry = _RecordingRegistry()
    _patch_cacheable_pipeline(monkeypatch, escalation, scheduled)
    monkeypatch.setattr(escalation, "get_llm_router_service", lambda: Router())
    monkeypatch.setattr(escalation, "response_registry", registry)

    result = asyncio.run(
        escalation.escalate(
            interaction=_interaction("cache"),
            messages=[{"role": "user", "content": "Current question"}],
        )
    )

    assert result.escalation_status == "answered"
    assert result.escalated_response.content == "The capital of Fra"
    assert scheduled == [], f"a truncated escalation was cached: {scheduled}"
    assert registry.kwargs["response_id"] is None


def test_truncated_external_escalation_is_answered_but_not_cached(monkeypatch):
    """The sibling of the local guard above: the provider's own finish_reason
    is the signal, and it reaches the same store decision."""
    from app.schemas.chat import ExternalLLMResponse
    from app.services import escalation

    class External:
        async def generate_response(self, request, provider, api_key):
            return ExternalLLMResponse(
                text="The capital of Fra",
                model_used=request.model,
                prompt_tokens=1,
                completion_tokens=2,
                latency_ms=3,
                finish_reason="length",
            )

    @contextmanager
    def fake_session():
        yield object()

    scheduled = []
    registry = _RecordingRegistry()
    _patch_cacheable_pipeline(monkeypatch, escalation, scheduled)
    monkeypatch.setattr(escalation, "response_registry", registry)
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
            messages=[{"role": "user", "content": "Current question"}],
        )
    )

    assert result.escalation_status == "answered"
    assert result.escalated_response.content == "The capital of Fra"
    assert scheduled == [], f"a truncated escalation was cached: {scheduled}"
    assert registry.kwargs["response_id"] is None


def test_untruncated_external_escalation_is_still_cached(monkeypatch):
    """Control: the guard must key on the provider's signal, not refuse every
    external escalation."""
    from app.schemas.chat import ExternalLLMResponse
    from app.services import escalation

    class External:
        async def generate_response(self, request, provider, api_key):
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

    scheduled = []
    registry = _RecordingRegistry()
    _patch_cacheable_pipeline(monkeypatch, escalation, scheduled)
    monkeypatch.setattr(escalation, "response_registry", registry)
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

    asyncio.run(
        escalation.escalate(
            interaction=_interaction("local"),
            messages=[{"role": "user", "content": "Current question"}],
        )
    )

    assert [entry["answer"] for entry in scheduled] == ["external better answer"]
    assert registry.kwargs["response_id"] is not None


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
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "passed"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("cache"),
            query="Current question",
            history=[{"role": "user", "content": "Old question"}],
            answer="better answer",
            truncated=False,
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
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "query too short"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("cache"),
            query="Hi",
            history=[],
            answer="hello",
            truncated=False,
        )
    )

    assert response_id is None
    assert scheduled == []


def test_cache_helper_refuses_to_store_an_empty_answer(monkeypatch):
    """A safety-blocked provider response can arrive as empty text with
    finish_reason normalized to "stop" - not truncated, but still not an
    answer worth caching. Mirrors the main pipeline's own guard."""
    from app.services import escalation

    class Enricher:
        async def enrich(self, query, history):
            return query

    class Normalizer:
        async def normalize(self, enriched):
            return "normalized current question"

    scheduled = []
    monkeypatch.setattr(escalation, "get_context_enricher_service", lambda: Enricher())
    monkeypatch.setattr(escalation, "get_normalizer_service", lambda: Normalizer())
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "passed"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("cache"),
            query="Current question",
            history=[],
            answer="   ",
            truncated=False,
        )
    )

    assert response_id is None
    assert scheduled == []


def test_cache_helper_refuses_to_store_when_parent_is_attachment_anchored(monkeypatch):
    """A negative-feedback escalation of a cache hit re-answers from message
    history alone - never the original image/file - so if the parent cache
    entry was attachment-anchored, the blind answer must not be stored as an
    ungated text entry."""
    from app.services import escalation

    class Enricher:
        async def enrich(self, query, history):
            return query

    class Normalizer:
        async def normalize(self, enriched):
            return "normalized current question"

    class Memory:
        def get_entry_metadata(self, entry_id):
            assert entry_id == "docid123"
            return {"file_sha": "abc123", "file_kind": "pdf"}

    scheduled = []
    monkeypatch.setattr(escalation, "get_context_enricher_service", lambda: Enricher())
    monkeypatch.setattr(escalation, "get_normalizer_service", lambda: Normalizer())
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "passed"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))
    monkeypatch.setattr(escalation, "get_memory_service", lambda namespace: Memory())

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("cache", response_id="acme__eng:docid123"),
            query="Summarise this document",
            history=[],
            answer="It's a summary the model made up without seeing the file",
            truncated=False,
        )
    )

    assert response_id is None
    assert scheduled == []


def test_cache_helper_stores_when_parent_is_plain_text(monkeypatch):
    """Control: a cache-tier parent with no attachment metadata is unaffected
    by the new guard."""
    from app.services import escalation

    class Enricher:
        async def enrich(self, query, history):
            return query

    class Normalizer:
        async def normalize(self, enriched):
            return "normalized current question"

    class Memory:
        def get_entry_metadata(self, entry_id):
            return {"answer": "hi", "score": 0.0}

    scheduled = []
    monkeypatch.setattr(escalation, "get_context_enricher_service", lambda: Enricher())
    monkeypatch.setattr(escalation, "get_normalizer_service", lambda: Normalizer())
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "passed"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))
    monkeypatch.setattr(escalation, "get_memory_service", lambda namespace: Memory())

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("cache", response_id="acme__eng:docid123"),
            query="Current question",
            history=[],
            answer="a real answer",
            truncated=False,
        )
    )

    assert response_id is not None
    assert scheduled != []


def test_cache_helper_skips_attachment_check_for_non_cache_parent(monkeypatch):
    """Only a cache-served parent can be attachment-anchored - a local/external
    parent's own stored answer (if any) is always plain text, so the guard
    must not even query the memory service for those, avoiding an unnecessary
    lookup on the far more common non-cache escalation path."""
    from app.services import escalation

    class Enricher:
        async def enrich(self, query, history):
            return query

    class Normalizer:
        async def normalize(self, enriched):
            return "normalized current question"

    def _unexpected_get_memory_service(namespace):
        raise AssertionError("must not query memory service for a non-cache parent")

    scheduled = []
    monkeypatch.setattr(escalation, "get_context_enricher_service", lambda: Enricher())
    monkeypatch.setattr(escalation, "get_normalizer_service", lambda: Normalizer())
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "passed"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))
    monkeypatch.setattr(escalation, "get_memory_service", _unexpected_get_memory_service)

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("local", response_id="acme__eng:docid123"),
            query="Current question",
            history=[],
            answer="a real answer",
            truncated=False,
        )
    )

    assert response_id is not None
    assert scheduled != []


def test_local_escalation_uses_default_max_tokens(monkeypatch):
    """The main path moved to DEFAULT_MAX_TOKENS=4096 precisely because 1024
    truncated ordinary answers - escalation must not stay capped at the old
    default."""
    from app.config import DEFAULT_MAX_TOKENS
    from app.services import escalation

    class Router:
        async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
            self.max_tokens = max_tokens
            return "a" * 5000, 11.0, "stop"

    router = Router()

    async def _cache_response_id_for_escalation(**kwargs):
        return None

    monkeypatch.setattr(escalation, "get_llm_router_service", lambda: router)
    monkeypatch.setattr(escalation, "response_registry", _RecordingRegistry())
    monkeypatch.setattr(escalation, "_cache_response_id_for_escalation", _cache_response_id_for_escalation)

    result = asyncio.run(
        escalation.escalate(
            interaction=_interaction("cache"),
            messages=[{"role": "user", "content": "Current question"}],
        )
    )

    assert result.escalation_status == "answered"
    assert router.max_tokens == DEFAULT_MAX_TOKENS


def test_external_escalation_uses_default_max_tokens(monkeypatch):
    from app.config import DEFAULT_MAX_TOKENS
    from app.schemas.chat import ExternalLLMResponse
    from app.services import escalation

    class External:
        async def generate_response(self, request, provider, api_key):
            self.request = request
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
        return None

    monkeypatch.setattr(escalation, "response_registry", _RecordingRegistry())
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
    assert external.request.max_tokens == DEFAULT_MAX_TOKENS


def test_cache_helper_refuses_to_store_a_truncated_answer(monkeypatch):
    """Both escalation branches store through this helper, so the truncation
    rule lives here rather than twice at the call sites: a cut-off answer is
    what every later match would be served, labelled finish_reason="stop"."""
    from app.services import escalation

    class Enricher:
        async def enrich(self, query, history):
            return query

    class Normalizer:
        async def normalize(self, enriched):
            return "normalized current question"

    scheduled = []
    monkeypatch.setattr(escalation, "get_context_enricher_service", lambda: Enricher())
    monkeypatch.setattr(escalation, "get_normalizer_service", lambda: Normalizer())
    monkeypatch.setattr(escalation.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "passed"))
    monkeypatch.setattr(escalation, "_schedule_escalation_cache_store", lambda **kwargs: scheduled.append(kwargs))

    response_id = asyncio.run(
        escalation._cache_response_id_for_escalation(
            interaction=_interaction("cache"),
            query="Current question",
            history=[],
            answer="The capital of Fra",
            truncated=True,
        )
    )

    assert response_id is None
    assert scheduled == []
