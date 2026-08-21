import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.memory_chromaDB import CacheLookupResult
from tests.conftest import StreamingLocalRouterMixin

# /v1/chat/completions requires a valid workspace API key (401 otherwise).
# Every test client sends this token; the autouse fixture below makes the key
# cache accept it. Tests that stub _KEY_CACHE.resolve themselves override it.
_AUTH = {"Authorization": "Bearer test-key"}


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class StubEnricher:
    async def enrich(self, message: str, history: list[dict]) -> str:
        return message


class RewritingEnricher:
    async def enrich(self, message: str, history: list[dict]) -> str:
        return "What is the capital of France?"


class StubNormalizer:
    async def normalize(self, raw_query: str) -> str:
        return raw_query.lower()


class StubAdjuster:
    async def generalize(self, answer: str) -> str:
        return answer

    async def adjust(self, original_query: str, general_answer: str) -> str:
        return general_answer


class MarkerAdjuster:
    """Returns a value distinguishable from general_answer, so a test can
    prove whether adjust() ran just by inspecting the served content -
    StubAdjuster's passthrough can't tell a skip from a no-op rewrite."""

    async def generalize(self, answer: str) -> str:
        return answer

    async def adjust(self, original_query: str, general_answer: str) -> str:
        return "ADJUSTED: " + general_answer


class StubRouter(StreamingLocalRouterMixin):
    async def generate_local_response(self, query: str, history=None, max_tokens=1024, system_prompt=None):
        return "Paris is the capital of France.", 12.0, "stop"


class TruncatedStubRouter(StreamingLocalRouterMixin):
    """Generation that spent its whole token budget: Ollama's own signal says
    "length", and the text itself reads as a clean prefix."""

    async def generate_local_response(self, query: str, history=None, max_tokens=1024, system_prompt=None):
        return "Paris is the capital of Fra", 12.0, "length"


class StubClassifier:
    calls = 0

    def predict_complexity(self, query: str) -> dict:
        self.calls += 1
        return {"complexity": "easy", "score": 0.0, "task_type": "qa"}


class HardClassifier:
    def predict_complexity(self, query: str) -> dict:
        return {"complexity": "hard", "score": 0.99, "task_type": "qa"}


class EasyLabelHighScoreClassifier:
    def predict_complexity(self, query: str) -> dict:
        return {"complexity": "easy", "score": 0.42, "task_type": "qa"}


class StubExternalLLM:
    async def generate_response(self, request, provider=None, api_key=None):
        raise AssertionError("External LLM should not be called for easy query smoke test")


class StubMemory:
    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(hit=False)

    def check_cache(self, clean_query: str):
        return None


class StubNearestMissMemory:
    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=False,
            nearest_distance=0.23456,
            nearest_prompt="capital city of france",
        )

    def check_cache(self, clean_query: str):
        return None


class StubNonLatin1NearestMissMemory:
    """Nearest cache prompt contains an em-dash (U+2014) - not Latin-1
    encodable, which used to crash Starlette's header encoding (report
    dejaq-big-eval-v2 section 9.1, queries q265/q369)."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=False,
            nearest_distance=0.23456,
            nearest_prompt="the treaty — signed in 1848 — ended the war",
        )

    def check_cache(self, clean_query: str):
        return None


class StubHitMemory:
    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer="Cached Paris answer.",
            entry_id="doc123",
            distance=0.04,
            matched_query="capital of france",
            nearest_distance=0.04,
            nearest_prompt="capital of france",
        )

    def check_cache(self, clean_query: str):
        return ("Cached Paris answer.", "doc123", 0.04, "capital of france")

    def increment_hit_count(self, doc_id: str):
        return None


class StubHitMemoryVeryClose:
    """Same shape as StubHitMemory but at a distance below
    VALIDATOR_SKIP_DISTANCE (0.003) as well as ADJUSTER_SKIP_DISTANCE -
    for tests that need the validator itself skipped, not just adjust()."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer="Cached Paris answer.",
            entry_id="doc123",
            distance=0.001,
            matched_query="capital of france",
            nearest_distance=0.001,
            nearest_prompt="capital of france",
        )

    def check_cache(self, clean_query: str):
        return ("Cached Paris answer.", "doc123", 0.001, "capital of france")

    def increment_hit_count(self, doc_id: str):
        return None


class StubNonLatin1HitMemory:
    """Matched cache query contains a curly apostrophe (U+2019) - the sibling
    free-text header (x-dejaq-cache-matched-query) that carries the same risk
    as x-dejaq-nearest-cache-prompt but wasn't the one that crashed first."""

    MATCHED_QUERY = "what’s the capital of france?"  # curly apostrophe, U+2019

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer="Cached Paris answer.",
            entry_id="doc123",
            distance=0.04,
            matched_query=self.MATCHED_QUERY,
            nearest_distance=0.04,
            nearest_prompt=self.MATCHED_QUERY,
        )

    def check_cache(self, clean_query: str):
        return ("Cached Paris answer.", "doc123", 0.04, self.MATCHED_QUERY)

    def increment_hit_count(self, doc_id: str):
        return None


class StubHitMemoryBeyondAdjustSkip:
    """Trusted-tier hit (distance well under CACHE_TRUST_DISTANCE) but past
    ADJUSTER_SKIP_DISTANCE - adjust() must still run for this one."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer="Cached Paris answer.",
            entry_id="docfar",
            distance=0.10,
            matched_query="capital of france",
            nearest_distance=0.10,
            nearest_prompt="capital of france",
        )

    def check_cache(self, clean_query: str):
        return None

    def increment_hit_count(self, doc_id: str):
        return None


class StubBandMemory:
    """Cache hit in the validator-guarded band (requires_validation=True)."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer="Cached Paris answer.",
            entry_id="docband",
            distance=0.18,
            matched_query="capital of france",
            nearest_distance=0.18,
            nearest_prompt="capital of france",
            requires_validation=True,
        )

    def check_cache(self, clean_query: str):
        return None

    def increment_hit_count(self, doc_id: str):
        return None


class StubRescueMemory:
    """Cache hit from the lexical-rescue tier (past band, word-aligned)."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer="Cached Moscow answer.",
            entry_id="docrescue",
            distance=0.40,
            matched_query="what is the capital of russia?",
            nearest_distance=0.40,
            nearest_prompt="what is the capital of russia?",
            requires_validation=True,
            rescued=True,
        )

    def check_cache(self, clean_query: str):
        return None

    def increment_hit_count(self, doc_id: str):
        return None


class StubMismatchBandMemory:
    """Band hit whose stored query differs by one word (list vs string)."""

    def lookup_cache(self, clean_query: str):
        return CacheLookupResult(
            hit=True,
            generalized_answer="Use s[::-1].",
            entry_id="docswap",
            distance=0.11,
            matched_query="how do i reverse a string in python?",
            nearest_distance=0.11,
            nearest_prompt="how do i reverse a string in python?",
            requires_validation=False,
            mismatches=(("list", "string"),),
        )

    def check_cache(self, clean_query: str):
        return None

    def increment_hit_count(self, doc_id: str):
        return None


class HintCapturingValidator:
    def __init__(self) -> None:
        self.hint = "UNSET"

    async def validate(self, new_query, cached_query, cached_answer, mismatch_hint=None):
        self.hint = mismatch_hint
        return True, "VALID"


class StubValidatorValid:
    async def validate(self, new_query, cached_query, cached_answer):
        return True, "VALID"


class StubValidatorInvalid:
    async def validate(self, new_query, cached_query, cached_answer):
        return False, "INVALID"


class ExplodingValidator:
    async def validate(self, *args, **kwargs):
        raise AssertionError("validator should not be called")


def no_stored_credential(session, workspace_id, provider):
    """Stub credential lookup: this workspace has none, and none is not an error.

    Replaces the router's get_workspace_provider_key, which reads the row before
    it needs an encryption key - so a test needs neither.
    """
    return None


def stored_credential(key: str, providers: tuple[str, ...] | None = None):
    """Stub credential lookup that hands back `key` (for `providers`, if given)."""

    def _lookup(session, workspace_id, provider):
        if providers is not None and provider not in providers:
            return None
        return key

    return _lookup


class CapturingRegistry:
    def __init__(self, interaction_id: str = "int_test") -> None:
        self.interaction_id = interaction_id
        self.calls: list[dict] = []

    async def register(self, **kwargs):
        self.calls.append(kwargs)
        from app.services.response_registry import ResponseInteraction

        return ResponseInteraction(
            interaction_id=self.interaction_id,
            workspace_id=kwargs["workspace_id"],
            workspace_slug=kwargs["workspace_slug"],
            department=kwargs["department"],
            cache_namespace=kwargs["cache_namespace"],
            served_tier=kwargs["served_tier"],
            response_id=kwargs["response_id"],
            message_hash="hash",
            created_at="2026-01-01T00:00:00+00:00",
            escalation_attempted=False,
            escalation_attempted_at=None,
        )


def test_chat_completions_smoke_preserves_response_shape(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
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
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "Paris is the capital of France."
    assert response.headers["x-dejaq-model-used"] == openai_compat.LOCAL_LLM_MODEL_NAME
    assert "x-dejaq-conversation-id" in response.headers


def test_local_answer_registers_interaction_and_emits_tier_headers(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    registry = CapturingRegistry("int_local")
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(openai_compat, "response_registry", registry, raising=False)

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
    assert response.headers["x-dejaq-interaction-id"] == "int_local"
    assert response.headers["x-dejaq-tier"] == "local"
    assert registry.calls
    assert registry.calls[0]["served_tier"] == "local"
    assert registry.calls[0]["response_id"] is None


def test_cache_answer_registers_interaction_and_emits_tier_headers(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    registry = CapturingRegistry("int_cache")
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "response_registry", registry, raising=False)

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
    assert response.headers["x-dejaq-interaction-id"] == "int_cache"
    assert response.headers["x-dejaq-tier"] == "cache"
    assert response.headers["x-dejaq-response-id"].endswith(":doc123")
    assert registry.calls[0]["served_tier"] == "cache"
    assert registry.calls[0]["response_id"].endswith(":doc123")


def test_adjust_skipped_for_close_single_turn_repeat(monkeypatch):
    """ADJUSTER_SKIP_DISTANCE: a single-turn near-duplicate of a cached
    question (distance 0.001, no prior conversation) must serve the stored
    answer verbatim - no adjust() call, no validator call. Uses an
    ExplodingValidator to prove the validator is never reached either (it
    already skips below VALIDATOR_SKIP_DISTANCE independent of this change);
    MarkerAdjuster proves adjust() specifically was skipped, since its output
    would be distinguishable from the raw cached text."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", MarkerAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", ExplodingValidator())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemoryVeryClose())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "what is teh capitol of frnace?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "Cached Paris answer."


def test_adjust_runs_for_single_turn_hit_beyond_skip_distance(monkeypatch):
    """A single-turn hit past ADJUSTER_SKIP_DISTANCE (distance 0.10, still
    inside the trusted tier) is not close enough to assume there is no tone
    gap - adjust() must still run."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", MarkerAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", StubValidatorValid())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemoryBeyondAdjustSkip())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "what's the capital of france anyway?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "ADJUSTED: Cached Paris answer."


def test_adjust_runs_for_multiturn_hit_even_when_close(monkeypatch):
    """The single-turn restriction is what protects a genuine 'give me the
    short version' follow-up (see config.py:ADJUSTER_SKIP_DISTANCE): even at
    a distance inside the skip window, a hit reached through prior
    conversation history must still go through adjust(), since only the
    conversation - not the distance - can tell a repeat from a rewrite ask."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", MarkerAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", ExplodingValidator())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemoryVeryClose())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "Cached Paris answer."},
                {"role": "user", "content": "give me the short version"},
            ],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "ADJUSTED: Cached Paris answer."


def test_cache_miss_includes_difficulty_and_nearest_cache_headers(monkeypatch, caplog):
    async def _noop_log(*args, **kwargs):
        return None

    class ScoredClassifier:
        def predict_complexity(self, query: str) -> dict:
            return {"complexity": "easy", "score": 0.42, "task_type": "qa"}

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", ScoredClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubNearestMissMemory())
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash",
            routing_threshold=0.9,
        ),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app, headers=_AUTH)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "What is the capital of France?"}],
                "stream": False,
            },
        )

    assert response.status_code == 200
    assert response.headers["x-dejaq-prompt-difficulty-score"] == "0.4200"
    assert response.headers["x-dejaq-nearest-cache-distance"] == "0.2346"
    assert response.headers["x-dejaq-nearest-cache-prompt"] == "capital city of france"

    done = next(
        record.message
        for record in caplog.records
        if record.name == "dejaq.router.openai_compat" and record.message.startswith("done cache=miss")
    )
    assert "difficulty_score=0.4200" in done
    assert "nearest_distance=0.2346" in done
    assert "nearest_prompt=capital city of france" in done


def test_cache_miss_logs_enriched_prompt_when_enricher_succeeds(monkeypatch, caplog):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", RewritingEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app, headers=_AUTH)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "What is its capital?"}],
                "stream": False,
            },
        )

    assert response.status_code == 200
    done = next(
        record.message
        for record in caplog.records
        if record.name == "dejaq.router.openai_compat" and record.message.startswith("done cache=miss")
    )
    assert "enriched_prompt=What is the capital of France?" in done


def test_cache_miss_omits_nearest_cache_headers_when_collection_empty(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
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
    assert "x-dejaq-nearest-cache-distance" not in response.headers
    assert "x-dejaq-nearest-cache-prompt" not in response.headers


def test_cache_hit_includes_nearest_cache_headers_without_difficulty_score(monkeypatch, caplog):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "What is the capital of France?"}],
                "stream": False,
            },
        )

    assert response.status_code == 200
    assert response.headers["x-dejaq-cache-distance"] == "0.0400"
    assert response.headers["x-dejaq-cache-matched-query"] == "capital of france"
    assert response.headers["x-dejaq-nearest-cache-distance"] == "0.0400"
    assert response.headers["x-dejaq-nearest-cache-prompt"] == "capital of france"
    assert "x-dejaq-prompt-difficulty-score" not in response.headers

    done = next(
        record.message
        for record in caplog.records
        if record.name == "dejaq.router.openai_compat" and record.message.startswith("done cache=hit")
    )
    assert "nearest_distance=0.0400" in done
    assert "nearest_prompt=capital of france" in done
    assert "difficulty_score=" not in done


def test_force_easy_local_header_skips_classifier(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    class ExplodingClassifier:
        def predict_complexity(self, query: str) -> dict:
            raise AssertionError("classifier should be skipped")

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", ExplodingClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        headers={"X-DejaQ-Routing-Mode": "easy_local"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-dejaq-model-used"] == openai_compat.LOCAL_LLM_MODEL_NAME


def test_force_hard_external_header_skips_classifier(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    class ExplodingClassifier:
        def predict_complexity(self, query: str) -> dict:
            raise AssertionError("classifier should be skipped")

    monkeypatch.setattr(openai_compat, "EXTERNAL_MODEL_NAME", "gemini-2.5-flash")
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", ExplodingClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat, "get_workspace_provider_key", no_stored_credential)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        headers={"X-DejaQ-Routing-Mode": "hard_external"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Explain a hard thing."}],
            "stream": False,
        },
    )

    assert response.status_code == 402
    assert response.json()["detail"].startswith("No google API key configured")


def test_auto_routing_uses_org_threshold_zero_to_route_external(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    class CapturingExternalLLM:
        async def generate_response(self, request, provider=None, api_key=None):
            self.request = request
            self.provider = provider
            self.api_key = api_key
            from app.schemas.chat import ExternalLLMResponse

            return ExternalLLMResponse(
                text="external answer",
                model_used=request.model,
                prompt_tokens=5,
                completion_tokens=6,
                latency_ms=10.0,
            )

    external = CapturingExternalLLM()

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", EasyLabelHighScoreClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", external)
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="gpt-5.4-mini",
            routing_threshold=0.0,
        ),
    )
    from cryptography.fernet import Fernet

    monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(
        openai_compat, "get_workspace_provider_key", stored_credential("sk-openai-live")
    )

    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 123))

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer org-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "external answer"
    assert response.headers["x-dejaq-prompt-difficulty"] == "hard"
    assert response.headers["x-dejaq-model-used"] == "gpt-5.4-mini"
    assert external.provider == "openai"
    assert external.api_key == "sk-openai-live"
    assert external.request.model == "gpt-5.4-mini"


def test_external_route_reports_real_provider_usage_not_heuristic(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    class CapturingExternalLLM:
        async def generate_response(self, request, provider=None, api_key=None):
            from app.schemas.chat import ExternalLLMResponse

            # Real provider counts (as Anthropic returns them) deliberately far
            # from what len(text.split()) * 1.3 would compute for this short
            # query/answer pair - if the route falls back to the heuristic,
            # these assertions fail.
            return ExternalLLMResponse(
                text="short answer",
                model_used=request.model,
                prompt_tokens=44,
                completion_tokens=300,
                latency_ms=10.0,
            )

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", CapturingExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(
        openai_compat,
        "get_workspace_provider_key",
        stored_credential("sk-ant-live", providers=("anthropic",)),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="claude-sonnet-4-6",
            routing_threshold=0.75,
        ),
    )

    from cryptography.fernet import Fernet

    monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Explain a hard thing."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["prompt_tokens"] == 44
    assert usage["completion_tokens"] == 300
    assert usage["total_tokens"] == 344


def test_force_hard_external_uses_org_external_model_provider(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    class ExplodingClassifier:
        def predict_complexity(self, query: str) -> dict:
            raise AssertionError("classifier should be skipped")

    class CapturingExternalLLM:
        async def generate_response(self, request, provider=None, api_key=None):
            self.request = request
            self.provider = provider
            self.api_key = api_key
            from app.schemas.chat import ExternalLLMResponse

            return ExternalLLMResponse(
                text="forced external answer",
                model_used=request.model,
                prompt_tokens=5,
                completion_tokens=6,
                latency_ms=10.0,
            )

    external = CapturingExternalLLM()

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", ExplodingClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", external)
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="claude-sonnet-4-6",
            routing_threshold=0.75,
        ),
    )
    from cryptography.fernet import Fernet

    monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(
        openai_compat,
        "get_workspace_provider_key",
        stored_credential("sk-ant-live", providers=("anthropic",)),
    )

    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 123))

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer org-key",
            "X-DejaQ-Routing-Mode": "hard_external",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Explain a hard thing."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-dejaq-model-used"] == "claude-sonnet-4-6"
    assert external.provider == "anthropic"
    assert external.api_key == "sk-ant-live"
    assert external.request.model == "claude-sonnet-4-6"


def test_weak_cpu_profile_uses_weak_local_services(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    class WeakRouter(StreamingLocalRouterMixin):
        model_name = "qwen_0_5b"

        async def generate_local_response(self, query: str, history=None, max_tokens=1024, system_prompt=None):
            return "weak local answer", 10.0, "stop"

    monkeypatch.setattr(openai_compat, "get_context_enricher_service", lambda model_name=None: StubEnricher())
    monkeypatch.setattr(openai_compat, "get_normalizer_service", lambda model_name=None: StubNormalizer())
    monkeypatch.setattr(openai_compat, "get_context_adjuster_service", lambda **kwargs: StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_llm_router_service", lambda model_name=None: WeakRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        headers={
            "X-DejaQ-Model-Profile": "weak_cpu",
            "X-DejaQ-Routing-Mode": "easy_local",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "weak local answer"
    assert response.headers["x-dejaq-model-used"] == "qwen_0_5b"


def test_services_for_model_profile_resolves_overridden_new_roles_only(monkeypatch):
    """enricher/normalizer/validator each get a freshly-resolved service only
    when this workspace overrides that specific role - the same
    resolve-only-if-overridden contract slice 1 established for
    local_model/generalizer_model/adjuster_model, extended to the three
    roles this slice adds."""
    resolved_calls: dict[str, str] = {}

    def _tracking_enricher(model_name=None, **kwargs):
        if model_name is not None:
            resolved_calls["enricher"] = model_name
        return StubEnricher()

    def _tracking_normalizer(model_name=None, **kwargs):
        if model_name is not None:
            resolved_calls["normalizer"] = model_name
        return StubNormalizer()

    def _tracking_validator(model_name=None, **kwargs):
        if model_name is not None:
            resolved_calls["validator"] = model_name
        return object()

    monkeypatch.setattr(openai_compat, "get_context_enricher_service", _tracking_enricher)
    monkeypatch.setattr(openai_compat, "get_normalizer_service", _tracking_normalizer)
    monkeypatch.setattr(openai_compat, "get_validator_service", _tracking_validator)

    llm_config = openai_compat.EffectiveLlmConfig(
        external_model="gemini-2.5-flash",
        routing_threshold=0.3,
        normalizer_model="gemma4:e4b",
        normalizer_model_overridden=True,
        validator_model="gemma4:e4b",
        validator_model_overridden=True,
        # enricher deliberately left un-overridden.
    )

    services = openai_compat._services_for_model_profile(openai_compat.MODEL_PROFILE_DEFAULT, llm_config)

    assert resolved_calls == {"normalizer": "gemma4:e4b", "validator": "gemma4:e4b"}
    assert "enricher" not in resolved_calls
    assert services.enricher is openai_compat._enricher


def test_services_for_model_profile_resolves_overridden_prompt_with_no_model_override(monkeypatch):
    """A workspace that overrides only a role's prompt (model left default)
    must still get a freshly-resolved service carrying that prompt - not the
    shared default-model singleton, which would silently ignore it."""
    captured: dict[str, tuple] = {}

    def _tracking_normalizer(model_name=None, system_prompt=None, num_ctx=None):
        captured["normalizer"] = (model_name, system_prompt)
        return StubNormalizer()

    monkeypatch.setattr(openai_compat, "get_normalizer_service", _tracking_normalizer)

    llm_config = openai_compat.EffectiveLlmConfig(
        external_model="gemini-2.5-flash",
        routing_threshold=0.3,
        normalizer_system_prompt="Custom normalizer prompt.",
        normalizer_system_prompt_overridden=True,
        # normalizer_model deliberately left un-overridden.
    )

    openai_compat._services_for_model_profile(openai_compat.MODEL_PROFILE_DEFAULT, llm_config)

    assert captured["normalizer"] == (None, "Custom normalizer prompt.")


def test_celery_store_keeps_legacy_args_and_sends_profile_header(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    captured: dict[str, object] = {}

    class FakeTask:
        def apply_async(self, *, args, headers, ignore_result=False, kwargs=None):
            captured["args"] = args
            captured["headers"] = headers
            captured["kwargs"] = kwargs

    monkeypatch.setattr(openai_compat, "get_context_enricher_service", lambda model_name=None: StubEnricher())
    monkeypatch.setattr(openai_compat, "get_normalizer_service", lambda model_name=None: StubNormalizer())
    monkeypatch.setattr(openai_compat, "get_context_adjuster_service", lambda **kwargs: StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_llm_router_service", lambda model_name=None: StubRouter())
    monkeypatch.setattr(openai_compat, "generalize_and_store_task", FakeTask())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", True)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        headers={
            "X-DejaQ-Model-Profile": "weak_cpu",
            "X-DejaQ-Routing-Mode": "easy_local",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert len(captured["args"]) == 5
    # Stored under the raw normalized query — no spell correction anywhere.
    assert captured["args"][0] == "what is the capital of france?"
    assert captured["headers"] == {"dejaq_model_profile": "weak_cpu"}
    # workspace_slug rides as a kwarg (plain string) so the Celery worker can
    # resolve its own fresh generalizer config instead of trusting a value
    # that may be minutes stale by the time the task actually runs.
    assert captured["kwargs"] == {"workspace_slug": "demo"}


def test_chat_completions_logs_compact_miss_summary(monkeypatch, caplog):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app, headers=_AUTH)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "What is the capital of France?"}],
                "stream": False,
            },
        )

    assert response.status_code == 200
    summaries = [
        record.message
        for record in caplog.records
        if record.name == "dejaq.router.openai_compat" and record.message.startswith("done ")
    ]
    assert len(summaries) == 1
    assert "cache=miss" in summaries[0]
    assert "route=local" in summaries[0]
    assert "store=skipped" in summaries[0]
    assert "steps=" in summaries[0]
    assert "enriched_prompt=What is the capital of France?" in summaries[0]


def test_chat_completions_logs_compact_hit_summary(monkeypatch, caplog):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "What is the capital of France?"}],
                "stream": False,
            },
        )

    assert response.status_code == 200
    summaries = [
        record.message
        for record in caplog.records
        if record.name == "dejaq.router.openai_compat" and record.message.startswith("done ")
    ]
    assert len(summaries) == 1
    assert "cache=hit" in summaries[0]
    assert "route=cache" in summaries[0]
    assert "model=cache" in summaries[0]


def test_chat_completions_logs_summary_when_enricher_fails(monkeypatch, caplog):
    class FailingEnricher:
        async def enrich(self, message: str, history: list[dict]) -> str:
            raise RuntimeError("boom")

    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", FailingEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app, headers=_AUTH)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "What is the capital of France?"}],
                "stream": False,
            },
        )

    assert response.status_code == 200
    assert any(record.exc_info for record in caplog.records if "Enricher failed" in record.message)
    assert any(
        record.name == "dejaq.router.openai_compat" and record.message.startswith("done ")
        for record in caplog.records
    )
    done = next(
        record.message
        for record in caplog.records
        if record.name == "dejaq.router.openai_compat" and record.message.startswith("done ")
    )
    assert "enriched_prompt=" not in done


def test_hard_query_without_org_credential_returns_402_without_env_fallback(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setenv("GEMINI_API_KEY", "platform-key-must-not-be-used")
    monkeypatch.setattr(openai_compat, "EXTERNAL_MODEL_NAME", "gemini-2.5-flash")
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat, "get_workspace_provider_key", no_stored_credential)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Explain a hard thing."}],
            "stream": False,
        },
    )

    assert response.status_code == 402
    assert response.json()["detail"].startswith("No google API key configured")


def test_band_hit_served_when_validator_valid(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    registry = CapturingRegistry("int_band")
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", StubValidatorValid())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubBandMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "response_registry", registry, raising=False)

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
    assert response.headers["x-dejaq-tier"] == "cache"
    assert response.headers["x-dejaq-validator-verdict"] == "valid"


def test_band_hit_falls_through_to_miss_when_validator_invalid(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "_validator", StubValidatorInvalid())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubBandMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
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
    assert response.json()["choices"][0]["message"]["content"] == "Paris is the capital of France."
    assert response.headers["x-dejaq-tier"] == "local"
    assert response.headers["x-dejaq-validator-verdict"] == "invalid"


def test_missing_api_key_returns_401():
    client = TestClient(app)  # no Authorization header
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )
    assert response.status_code == 401


def test_invalid_api_key_returns_401():
    client = TestClient(app, headers={"Authorization": "Bearer not-a-real-key"})
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )
    assert response.status_code == 401


def test_responses_endpoint_requires_api_key():
    client = TestClient(app)  # no Authorization header
    response = client.post(
        "/v1/responses",
        json={"model": "gpt-4o-mini", "input": "What is the capital of France?"},
    )
    assert response.status_code == 401


def test_rescued_hit_served_when_validator_valid(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    alias_calls: list[tuple] = []

    def _noop_alias(namespace, alias_query, source_entry_id):
        # record synchronously at call time; return a no-op coroutine for create_task
        alias_calls.append((namespace, alias_query, source_entry_id))

        async def _done():
            return None

        return _done()

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", StubValidatorValid())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubRescueMemory())
    monkeypatch.setattr(openai_compat, "_store_alias_bg", _noop_alias)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "CACHE_ALIAS_ENABLED", True)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "what is teh captial of rusia?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Cached Moscow answer."
    assert response.headers["x-dejaq-tier"] == "cache"
    assert response.headers["x-dejaq-validator-verdict"] == "valid"
    # Alias learning fired for the validated rescue hit
    assert alias_calls and alias_calls[0][2] == "docrescue"


def test_rescued_hit_misses_when_validator_invalid(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "_validator", StubValidatorInvalid())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubRescueMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "what is teh captial of rusia?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-dejaq-tier"] == "local"
    assert response.headers["x-dejaq-validator-verdict"] == "invalid"


def test_mismatch_hint_reaches_validator(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    validator = HintCapturingValidator()
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_validator", validator)
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMismatchBandMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "how do i reverse a list in python?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert validator.hint == "'list' vs 'string'"


def test_no_alias_stored_for_trusted_hit(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    alias_calls: list[tuple] = []

    def _noop_alias(namespace, alias_query, source_entry_id):
        # record synchronously at call time; return a no-op coroutine for create_task
        alias_calls.append((namespace, alias_query, source_entry_id))

        async def _done():
            return None

        return _done()

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemory())
    monkeypatch.setattr(openai_compat, "_store_alias_bg", _noop_alias)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "CACHE_ALIAS_ENABLED", True)

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
    assert response.headers["x-dejaq-tier"] == "cache"
    assert not alias_calls  # trusted hits don't need aliases


def _patch_for_truncation(monkeypatch, router):
    """Minimum wiring for a cache miss answered by `router`, no models loaded."""

    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    return TestClient(app, headers=_AUTH)


def _sse_events(response) -> list[dict]:
    """Parse `data:` payloads out of an SSE body, skipping the [DONE] sentinel."""
    import json

    return [
        json.loads(line[len("data: "):])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def test_truncated_miss_reports_length_on_chat_completions(monkeypatch):
    """The wire-level end of the truncation signal. Without it a client that
    sends a small max_tokens gets a cut-off answer labelled finish_reason=stop,
    i.e. told the model finished when it did not."""
    client = _patch_for_truncation(monkeypatch, TruncatedStubRouter())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "max_tokens": 8,
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["finish_reason"] == "length"


def test_untruncated_miss_still_reports_stop_on_chat_completions(monkeypatch):
    """Control for the three tests around it: honest reporting has to mean
    "length" only when the generator said so, not "length" everywhere."""
    client = _patch_for_truncation(monkeypatch, StubRouter())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )

    assert response.json()["choices"][0]["finish_reason"] == "stop"


def test_workspace_answer_budget_override_reaches_the_local_generator(monkeypatch):
    """Proves the override changes real behavior, not just a persisted number:
    a workspace's default_max_tokens override must be what a no-limit client
    request actually generates under - not the global DEFAULT_MAX_TOKENS."""

    captured: dict[str, int] = {}

    class RecordingRouter(StreamingLocalRouterMixin):
        async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
            captured["max_tokens"] = max_tokens
            return "Paris is the capital of France.", 12.0, "stop"

    client = _patch_for_truncation(monkeypatch, RecordingRouter())
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash",
            routing_threshold=0.3,
            default_max_tokens=777,
        ),
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert captured["max_tokens"] == 777
    assert captured["max_tokens"] != openai_compat.DEFAULT_MAX_TOKENS


def test_truncated_miss_reports_length_on_the_final_stream_chunk(monkeypatch):
    client = _patch_for_truncation(monkeypatch, TruncatedStubRouter())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "max_tokens": 8,
            "stream": True,
        },
    )

    assert response.status_code == 200
    chunks = _sse_events(response)
    assert chunks[-1]["choices"][0]["finish_reason"] == "length"


def test_truncated_miss_reports_incomplete_on_responses(monkeypatch):
    """/v1/responses carries the same signal as a status, top-level and on the
    output item - an SDK reads either one."""
    client = _patch_for_truncation(monkeypatch, TruncatedStubRouter())

    response = client.post(
        "/v1/responses",
        json={
            "model": "gpt-4o-mini",
            "input": "What is the capital of France?",
            "max_output_tokens": 8,
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "incomplete"
    assert payload["output"][0]["status"] == "incomplete"
    assert payload["incomplete_details"] == {"reason": "max_output_tokens"}


def test_untruncated_miss_still_reports_completed_on_responses(monkeypatch):
    client = _patch_for_truncation(monkeypatch, StubRouter())

    response = client.post(
        "/v1/responses",
        json={"model": "gpt-4o-mini", "input": "What is the capital of France?", "stream": False},
    )

    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["output"][0]["status"] == "completed"
    assert payload["incomplete_details"] is None


def test_truncated_miss_reports_incomplete_on_streamed_responses(monkeypatch):
    """A client that branches on the SSE event type has to see the truncation
    there too - a `response.completed` event carrying `status: "incomplete"`
    says the opposite of what happened."""
    client = _patch_for_truncation(monkeypatch, TruncatedStubRouter())

    response = client.post(
        "/v1/responses",
        json={
            "model": "gpt-4o-mini",
            "input": "What is the capital of France?",
            "max_output_tokens": 8,
            "stream": True,
        },
    )

    assert response.status_code == 200
    events = _sse_events(response)
    item_done = [e for e in events if e.get("item", {}).get("status") == "incomplete"]
    assert item_done, "no output_item.done carried the incomplete status"
    assert "event: response.incomplete\n" in response.text
    assert "event: response.completed\n" not in response.text
    assert events[-1]["type"] == "response.incomplete"
    assert events[-1]["response"]["status"] == "incomplete"
    assert events[-1]["response"]["incomplete_details"] == {"reason": "max_output_tokens"}


def test_untruncated_miss_still_reports_completed_on_streamed_responses(monkeypatch):
    """Control: the completed path is untouched - same terminal event, no
    incomplete_details."""
    client = _patch_for_truncation(monkeypatch, StubRouter())

    response = client.post(
        "/v1/responses",
        json={"model": "gpt-4o-mini", "input": "What is the capital of France?", "stream": True},
    )

    assert response.status_code == 200
    events = _sse_events(response)
    assert "event: response.completed\n" in response.text
    assert "event: response.incomplete\n" not in response.text
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["status"] == "completed"
    assert events[-1]["response"]["incomplete_details"] is None


def test_hard_query_unmapped_external_model_returns_422(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "EXTERNAL_MODEL_NAME", "mystery-model")
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Explain a hard thing."}],
            "stream": False,
        },
    )

    assert response.status_code == 422
    assert "not mapped to a supported provider" in response.json()["detail"]


def test_cache_miss_with_non_latin1_nearest_prompt_does_not_crash(monkeypatch):
    """Regression for dejaq-big-eval-v2 report section 9.1 (q265/q369): an
    em-dash in the nearest cached prompt used to raise UnicodeEncodeError
    inside Starlette's header encoding and turn the whole request into a 500.
    Must now return 200 with a sanitized (not dropped) header."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", StubRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubNonLatin1NearestMissMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
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
    header = response.headers["x-dejaq-nearest-cache-prompt"]
    assert "—" not in header
    header.encode("latin-1")  # must not raise


def test_cache_hit_with_non_latin1_matched_query_does_not_crash(monkeypatch):
    """Sibling of the em-dash regression above: x-dejaq-cache-matched-query
    carries the same kind of free text (from the same stored-prompt source)
    and must go through the same sanitizing path, not just the header that
    happened to crash first."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubNonLatin1HitMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

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
    header = response.headers["x-dejaq-cache-matched-query"]
    assert "’" not in header
    header.encode("latin-1")  # must not raise
    assert response.headers["x-dejaq-nearest-cache-prompt"].encode("latin-1")


def test_cache_hit_includes_enriched_query_header_when_rewritten(monkeypatch):
    """RewritingEnricher stands in for a follow-up that genuinely got rewritten
    into a standalone question - the header must carry that rewritten text so
    the client can show it as the middle step between "You asked" and "Stored
    answer for"."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", RewritingEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "How many people died in that war?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-dejaq-enriched-query"] == "What is the capital of France?"


def test_cache_hit_omits_enriched_query_header_when_not_rewritten(monkeypatch):
    """enrich() returns the message unchanged for an already-standalone
    question (context_enricher.py:47) - the header must be absent entirely,
    not present and identical to the user's own words."""
    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

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
    assert "x-dejaq-enriched-query" not in response.headers


def test_cache_hit_with_non_latin1_enriched_query_does_not_crash(monkeypatch):
    """Sibling of the em-dash/curly-quote regressions above: the enriched
    question is free text in whatever language the user wrote in, and must go
    through the same _sanitize_headers path or a non-Latin-1 rewrite crashes
    the request the same way the matched-query header once did."""
    class NonLatin1Enricher:
        async def enrich(self, message: str, history: list[dict]) -> str:
            return "how many people died in the war — the one that ended in 1848?"

    async def _noop_log(*args, **kwargs):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", NonLatin1Enricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubHitMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app, headers=_AUTH)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "How many people died in that war?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    header = response.headers["x-dejaq-enriched-query"]
    assert "—" not in header
    header.encode("latin-1")  # must not raise


def test_sanitize_headers_covers_every_free_text_diagnostic_header():
    """Proves the shared choke point, not per-site patching: every free-text
    header declared in app/main.py's CORS expose_headers list must survive
    _sanitize_headers unencodable-latin1-safe. Numeric/enum headers are
    trivially safe by construction; this asserts the ones that carry raw
    stored/query text specifically. A new free-text header added to a headers
    dict without going through _sanitize_headers would not be caught by this
    test directly, but the two end-to-end tests above prove the two known
    free-text headers both route through it."""
    from app.main import app as fastapi_app

    expose_headers = None
    for middleware in fastapi_app.user_middleware:
        if middleware.kwargs.get("expose_headers"):
            expose_headers = middleware.kwargs["expose_headers"]
            break
    assert expose_headers is not None

    free_text_headers = {
        "x-dejaq-nearest-cache-prompt",
        "x-dejaq-cache-matched-query",
        "x-dejaq-enriched-query",
    }
    assert free_text_headers.issubset(set(expose_headers))

    poisoned = {name: "em—dash and curly ’ quote" for name in expose_headers}
    sanitized = openai_compat._sanitize_headers(poisoned)

    for name, value in sanitized.items():
        value.encode("latin-1")  # must not raise for any declared header
    for name in free_text_headers:
        assert "—" not in sanitized[name]
        assert "'" not in sanitized[name]

    clean = {"x-dejaq-tier": "cache", "x-dejaq-cache-distance": "0.0400"}
    assert openai_compat._sanitize_headers(clean) == clean
