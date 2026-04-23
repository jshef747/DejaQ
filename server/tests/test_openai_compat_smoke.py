from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat


class StubEnricher:
    async def enrich(self, message: str, history: list[dict]) -> str:
        return message


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
    def predict_complexity(self, query: str) -> dict:
        return {"complexity": "easy", "score": 0.0, "task_type": "qa"}


class StubExternalLLM:
    async def generate_response(self, request):
        raise AssertionError("External LLM should not be called for easy query smoke test")


class StubMemory:
    def check_cache(self, clean_query: str):
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
