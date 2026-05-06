from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services.memory_chromaDB import CacheLookupResult


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


class StubRouter:
    async def generate_local_response(self, query: str, history=None, max_tokens=1024, system_prompt=None):
        return "Paris is the capital of France.", 12.0


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
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app)
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
    assert response.headers["x-dejaq-model-used"] == openai_compat._LOCAL_MODEL_NAME
    assert "x-dejaq-conversation-id" in response.headers


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
        lambda org_slug, org_id: openai_compat.EffectiveLlmConfig(
            external_model="gemini-2.5-flash",
            routing_threshold=0.9,
        ),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app)

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
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app)

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
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app)
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

    client = TestClient(app)

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
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app)
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
    assert response.headers["x-dejaq-model-used"] == openai_compat._LOCAL_MODEL_NAME


def test_force_hard_external_header_skips_classifier(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    class ExplodingClassifier:
        def predict_complexity(self, query: str) -> dict:
            raise AssertionError("classifier should be skipped")

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", ExplodingClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app)
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
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda org_slug, org_id: openai_compat.EffectiveLlmConfig(
            external_model="gpt-5.4-mini",
            routing_threshold=0.0,
        ),
    )
    monkeypatch.setattr(
        openai_compat.CredentialService,
        "get_decrypted_key",
        lambda self, session, org_id, provider: "sk-openai-live",
    )

    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 123))

    client = TestClient(app)
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
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda org_slug, org_id: openai_compat.EffectiveLlmConfig(
            external_model="claude-sonnet-4-6",
            routing_threshold=0.75,
        ),
    )
    monkeypatch.setattr(
        openai_compat.CredentialService,
        "get_decrypted_key",
        lambda self, session, org_id, provider: "sk-ant-live" if provider == "anthropic" else None,
    )

    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 123))

    client = TestClient(app)
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

    class WeakRouter:
        model_name = "qwen_0_5b"

        async def generate_local_response(self, query: str, history=None, max_tokens=1024, system_prompt=None):
            return "weak local answer", 10.0

    monkeypatch.setattr(openai_compat, "get_context_enricher_service", lambda model_name=None: StubEnricher())
    monkeypatch.setattr(openai_compat, "get_normalizer_service", lambda model_name=None: StubNormalizer())
    monkeypatch.setattr(openai_compat, "get_context_adjuster_service", lambda **kwargs: StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_llm_router_service", lambda model_name=None: WeakRouter())
    monkeypatch.setattr(openai_compat, "_classifier", StubClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app)
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


def test_celery_store_keeps_legacy_args_and_sends_profile_header(monkeypatch):
    async def _noop_log(*args, **kwargs):
        return None

    captured: dict[str, object] = {}

    class FakeTask:
        def apply_async(self, *, args, headers):
            captured["args"] = args
            captured["headers"] = headers

    monkeypatch.setattr(openai_compat, "get_context_enricher_service", lambda model_name=None: StubEnricher())
    monkeypatch.setattr(openai_compat, "get_normalizer_service", lambda model_name=None: StubNormalizer())
    monkeypatch.setattr(openai_compat, "get_context_adjuster_service", lambda **kwargs: StubAdjuster())
    monkeypatch.setattr(openai_compat, "get_llm_router_service", lambda model_name=None: StubRouter())
    monkeypatch.setattr(openai_compat, "generalize_and_store_task", FakeTask())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (True, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", True)

    client = TestClient(app)
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
    assert captured["headers"] == {"dejaq_model_profile": "weak_cpu"}


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
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app)

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

    client = TestClient(app)

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
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)

    client = TestClient(app)

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
    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "_external_llm", StubExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)

    client = TestClient(app)
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

    client = TestClient(app)
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
