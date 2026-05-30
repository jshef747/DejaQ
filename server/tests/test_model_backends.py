import asyncio
import time

import httpx

from app.services.context_adjuster import ContextAdjusterService
from app.services.context_enricher import ContextEnricherService
from app.services.llm_router import LLMRouterService
from app.services.model_backends import CompletionRequest, OllamaBackend
from app.services.normalizer import NormalizerService


class FakeBackend:
    def __init__(self, response: str = "ok"):
        self.response = response
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> str:
        self.requests.append(request)
        return self.response


def test_ollama_backend_posts_chat_request():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "from ollama"}},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        transport=transport,
        base_url="http://ollama.test",
    )
    backend = OllamaBackend(
        base_url="http://ollama.test",
        timeout_seconds=5.0,
        client=client,
    )

    try:
        result = asyncio.run(
            backend.complete(
                CompletionRequest(
                    model_name="qwen_1_5b",
                    messages=[{"role": "user", "content": "hello"}],
                    max_tokens=32,
                    temperature=0.0,
                )
            )
        )
    finally:
        asyncio.run(client.aclose())

    assert result == "from ollama"
    assert captured["url"] == "http://ollama.test/api/chat"
    assert '"model":"qwen2.5:1.5b"' in captured["payload"]


def test_services_send_logical_model_names_to_backend():
    backend = FakeBackend("backend output")
    enricher = ContextEnricherService(backend=backend, model_name="qwen_1_5b")
    normalizer = NormalizerService(backend=backend, model_name="gemma_e2b")
    llm_router = LLMRouterService(backend=backend, model_name="gemma_local")
    adjuster = ContextAdjusterService(
        adjust_backend=backend,
        adjust_model_name="qwen_1_5b",
        generalize_backend=backend,
        generalize_model_name="phi_generalizer",
    )

    assert asyncio.run(enricher.enrich("hello", [{"role": "user", "content": "hi"}])) == "backend output"
    assert asyncio.run(normalizer.normalize("What is gravity?")) == "what is gravity?"
    assert asyncio.run(llm_router.generate_response("Hi", "easy")) == "backend output"
    assert asyncio.run(adjuster.generalize("Hello")) == "backend output"
    assert asyncio.run(adjuster.adjust("Hi", "Hello")) == "backend output"

    assert backend.requests[0].model_name == "qwen_1_5b"
    assert backend.requests[1].model_name == "gemma_local"
    assert backend.requests[2].model_name == "phi_generalizer"
    assert backend.requests[3].model_name == "qwen_1_5b"


def test_service_factory_builds_ollama_backend(monkeypatch):
    import app.config as config
    import app.services.service_factory as service_factory

    monkeypatch.setattr(config, "NORMALIZER_MODEL_NAME", "gemma_e2b")
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama.test")
    monkeypatch.setattr(config, "OLLAMA_TIMEOUT_SECONDS", 9.0)
    service_factory._backend = None
    service_factory._service_pool.clear()

    service = service_factory.get_normalizer_service()

    assert isinstance(service.backend, OllamaBackend)
    assert service.model_name == "gemma_e2b"


def test_service_factory_can_override_logical_model_for_temporary_profile(monkeypatch):
    import app.config as config
    import app.services.service_factory as service_factory

    monkeypatch.setattr(config, "ENRICHER_MODEL_NAME", "qwen_1_5b")
    service_factory._backend = None
    service_factory._service_pool.clear()

    default_service = service_factory.get_context_enricher_service()
    weak_service = service_factory.get_context_enricher_service(model_name="qwen_0_5b")

    assert default_service.model_name == "qwen_1_5b"
    assert weak_service.model_name == "qwen_0_5b"
    assert weak_service is service_factory.get_context_enricher_service(model_name="qwen_0_5b")
    assert weak_service is not default_service


def test_llm_router_uses_ollama_backend(monkeypatch):
    import app.config as config
    import app.services.service_factory as service_factory

    class FakeOllamaBackend:
        def __init__(self, base_url: str, timeout_seconds: float):
            self.base_url = base_url
            self.timeout_seconds = timeout_seconds

        async def complete(self, request: CompletionRequest) -> str:
            return f"ollama:{request.model_name}"

    monkeypatch.setattr(config, "LOCAL_LLM_MODEL_NAME", "gemma_local")
    monkeypatch.setattr(config, "OLLAMA_URL", "http://ollama.test")
    monkeypatch.setattr(config, "OLLAMA_TIMEOUT_SECONDS", 9.0)
    monkeypatch.setattr(service_factory, "OllamaBackend", FakeOllamaBackend)
    service_factory._backend = None
    service_factory._service_pool.clear()

    service = service_factory.get_llm_router_service()
    result = asyncio.run(service.generate_response("hello", "easy"))

    assert result == "ollama:gemma_local"


def test_ollama_backend_requests_can_overlap():
    class SleepingClient:
        async def post(self, url: str, json: dict) -> httpx.Response:
            await asyncio.sleep(0.2)
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "done"}},
                request=httpx.Request("POST", f"http://ollama.test{url}"),
            )

    backend = OllamaBackend(
        base_url="http://ollama.test",
        timeout_seconds=5.0,
        client=SleepingClient(),  # type: ignore[arg-type]
    )
    request = CompletionRequest(
        model_name="qwen_1_5b",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=16,
        temperature=0.0,
    )

    async def run_batch() -> float:
        started = time.perf_counter()
        await asyncio.gather(*(backend.complete(request) for _ in range(5)))
        return time.perf_counter() - started

    elapsed = asyncio.run(run_batch())
    assert elapsed < 0.7
