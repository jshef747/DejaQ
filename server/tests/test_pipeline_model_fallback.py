"""Regression tests for the day-2-drift fallback: a workspace pipeline
override names a model that was uninstalled from Ollama after it was saved.
Write-time validation (test_llm_config_service.py) can't catch this - these
tests cover the serve-time behavior instead: never a raw 500, always a
fallback to the shipped default, logged.
"""
import asyncio

import pytest

from app.services.context_adjuster import ContextAdjusterService
from app.services.llm_router import LLMRouterService
from app.services.model_backends import (
    CompletionRequest,
    CompletionResult,
    ModelBackend,
    ModelNotFoundError,
    OllamaBackend,
)


class _FailThenSucceedBackend:
    """Raises ModelNotFoundError for one specific model name; any other
    model name succeeds. Records every model_name it was called with."""

    def __init__(self, missing_model: str, response: str = "ok"):
        self.missing_model = missing_model
        self.response = response
        self.model_names_seen: list[str] = []

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.model_names_seen.append(request.model_name)
        if request.model_name == self.missing_model:
            raise ModelNotFoundError(request.model_name)
        return CompletionResult(text=self.response, done_reason="stop")


# ── OllamaBackend itself: raw-tag passthrough + 404 -> ModelNotFoundError ──


def test_resolve_model_passes_through_a_raw_tag_not_in_the_static_spec_dict():
    """Captain's decision: a workspace override names any installed Ollama
    tag directly, not just entries in MODEL_RUNTIME_SPECS. _resolve_model
    must no longer raise for that case - it must pass the tag through."""
    backend = OllamaBackend(base_url="http://ollama.test", timeout_seconds=5.0)

    assert backend._resolve_model("llama3.2:3b") == "llama3.2:3b"


def test_resolve_model_still_maps_a_registered_logical_name():
    backend = OllamaBackend(base_url="http://ollama.test", timeout_seconds=5.0)

    assert backend._resolve_model("gemma_local") == "gemma4:e4b"


def test_complete_raises_model_not_found_on_ollama_404(monkeypatch):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'ghost:1b' not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test")
    backend = OllamaBackend(base_url="http://ollama.test", timeout_seconds=5.0, client=client)

    with pytest.raises(ModelNotFoundError) as exc_info:
        asyncio.run(
            backend.complete(
                CompletionRequest(model_name="ghost:1b", messages=[{"role": "user", "content": "hi"}], max_tokens=8, temperature=0.0)
            )
        )
    asyncio.run(client.aclose())
    assert exc_info.value.model_name == "ghost:1b"


# ── Role-level fallback: generalizer, adjuster, local answering ──


def test_generalize_falls_back_to_shipped_default_when_override_is_uninstalled():
    from app.config import GENERALIZER_MODEL_NAME

    backend = _FailThenSucceedBackend(missing_model="a-since-uninstalled-tag", response="clean answer")
    service = ContextAdjusterService(
        adjust_backend=backend, adjust_model_name="qwen_1_5b",
        generalize_backend=backend, generalize_model_name="a-since-uninstalled-tag",
    )

    result = asyncio.run(service.generalize("some raw answer"))

    assert result == "clean answer"
    # 3 calls: the override (fails), the fallback default (succeeds but the
    # fake backend always reports done_reason="stop", which triggers
    # generalize()'s own stop-string retry - see context_adjuster.py), and
    # that retry, both against the fallback model from here on.
    assert backend.model_names_seen == [
        "a-since-uninstalled-tag", GENERALIZER_MODEL_NAME, GENERALIZER_MODEL_NAME,
    ]


def test_adjust_falls_back_to_shipped_default_when_override_is_uninstalled():
    from app.config import CONTEXT_ADJUSTER_MODEL_NAME

    backend = _FailThenSucceedBackend(missing_model="a-since-uninstalled-tag", response="output tone-matched")
    service = ContextAdjusterService(
        adjust_backend=backend, adjust_model_name="a-since-uninstalled-tag",
        generalize_backend=backend, generalize_model_name="gemma_e2b",
    )

    # "output" shares a content word with the cached answer so the
    # topic-consistency safety net doesn't swap in the cached answer here -
    # this test only cares about fallback routing.
    result = asyncio.run(service.adjust("hi", "output"))

    assert result == "output tone-matched"
    assert backend.model_names_seen == ["a-since-uninstalled-tag", CONTEXT_ADJUSTER_MODEL_NAME]


def test_local_answering_falls_back_to_shipped_default_when_override_is_uninstalled():
    from app.config import LOCAL_LLM_MODEL_NAME

    backend = _FailThenSucceedBackend(missing_model="a-since-uninstalled-tag", response="the answer")
    service = LLMRouterService(backend=backend, model_name="a-since-uninstalled-tag")

    text, _latency, done_reason = asyncio.run(service.generate_local_response("hi"))

    assert text == "the answer"
    assert done_reason == "stop"
    assert backend.model_names_seen == ["a-since-uninstalled-tag", LOCAL_LLM_MODEL_NAME]


def test_generalize_reraises_when_the_shipped_default_is_also_missing():
    """Not the day-2-drift case this feature covers - a genuinely broken
    Ollama install with no models at all. Must surface the error rather than
    loop forever retrying the same missing model."""
    from app.config import GENERALIZER_MODEL_NAME

    class _AlwaysMissingBackend:
        async def complete(self, request: CompletionRequest) -> CompletionResult:
            raise ModelNotFoundError(request.model_name)

    service = ContextAdjusterService(
        adjust_backend=_AlwaysMissingBackend(), adjust_model_name="qwen_1_5b",
        generalize_backend=_AlwaysMissingBackend(), generalize_model_name=GENERALIZER_MODEL_NAME,
    )

    with pytest.raises(ModelNotFoundError):
        asyncio.run(service.generalize("some raw answer"))
