import asyncio

import pytest

from app.schemas.chat import ExternalLLMRequest
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from app.utils.exceptions import ExternalAttachmentTooLargeError, ExternalAttachmentUnsupportedError
from tests._fake_llm_server import FakeLLMServer

pytestmark = pytest.mark.no_model

_OK_RESPONSE = {
    "id": "resp-1", "object": "chat.completion", "created": 1, "model": "fake-model",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}

# Groq's response transformer reads this extra field unconditionally.
_GROQ_OK_RESPONSE = {**_OK_RESPONSE, "service_tier": "default"}


def _request(model: str, **kw) -> ExternalLLMRequest:
    kw.setdefault("query", "What does this show?")
    return ExternalLLMRequest(
        system_prompt="Be useful.",
        model=model,
        max_tokens=64,
        **kw,
    )


def test_image_request_to_confirmed_text_only_model_raises_before_the_wire(monkeypatch):
    """groq/openai/gpt-oss-120b is confirmed text-only in LiteLLM's own
    catalog (the real Groq model this was measured against - see
    dejaq-acceptance-fixes report). Must never reach the network."""
    with FakeLLMServer([(200, _GROQ_OK_RESPONSE)]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")
        request = _request("groq/openai/gpt-oss-120b", image_b64="Zm9v", image_mime="image/png")
        with pytest.raises(ExternalAttachmentUnsupportedError) as exc_info:
            asyncio.run(client.generate_response(request, "sk-test"))

    assert exc_info.value.kind == "image"
    assert exc_info.value.model_name == "groq/openai/gpt-oss-120b"
    assert server.requests == []


def test_pdf_request_to_confirmed_text_only_model_raises_before_the_wire(monkeypatch):
    with FakeLLMServer([(200, _GROQ_OK_RESPONSE)]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")
        request = _request("groq/openai/gpt-oss-120b", file_b64="Zm9v", file_mime="application/pdf")
        with pytest.raises(ExternalAttachmentUnsupportedError) as exc_info:
            asyncio.run(client.generate_response(request, "sk-test"))

    assert exc_info.value.kind == "document"
    assert server.requests == []


def test_image_request_to_confirmed_vision_model_is_not_blocked(monkeypatch):
    with FakeLLMServer([(200, _OK_RESPONSE)]) as server:
        monkeypatch.setenv("OPENAI_API_BASE", f"{server.base_url}/v1")
        client = LiteLLMTransportClient("openai")
        request = _request("openai/gpt-4o", image_b64="Zm9v", image_mime="image/png")
        asyncio.run(client.generate_response(request, "sk-test"))

    assert len(server.requests) == 1
    content = server.requests[0]["messages"][-1]["content"]
    assert any(part.get("type") == "image_url" for part in content)


def test_image_request_to_a_model_litellm_has_no_catalog_entry_for_is_not_blocked(monkeypatch):
    """A model LiteLLM hasn't catalogued (older/newer id) is a data gap, not
    proof of incapability - it must reach the provider exactly as before
    this check existed, not be blocked on missing data."""
    with FakeLLMServer([(200, _OK_RESPONSE)]) as server:
        monkeypatch.setenv("OPENAI_API_BASE", f"{server.base_url}/v1")
        client = LiteLLMTransportClient("openai")
        request = _request("openai/some-unmapped-future-model", image_b64="Zm9v", image_mime="image/png")
        asyncio.run(client.generate_response(request, "sk-test"))

    assert len(server.requests) == 1


def test_streaming_path_is_also_gated(monkeypatch):
    with FakeLLMServer([(200, _GROQ_OK_RESPONSE)]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")
        request = _request("groq/openai/gpt-oss-120b", image_b64="Zm9v", image_mime="image/png")

        async def _drain():
            async for _ in client.stream_response(request, "sk-test"):
                pass

        with pytest.raises(ExternalAttachmentUnsupportedError):
            asyncio.run(_drain())

    assert server.requests == []


def test_text_only_request_is_never_gated(monkeypatch):
    with FakeLLMServer([(200, _GROQ_OK_RESPONSE)]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")
        request = _request("groq/openai/gpt-oss-120b")
        asyncio.run(client.generate_response(request, "sk-test"))

    assert len(server.requests) == 1


# --- Oversized inlined-text attachment (the token-budget gap fix #3 didn't cover) ---
# groq/openai/gpt-oss-120b is confirmed in LiteLLM's own catalog at
# max_input_tokens=131072 - a query well past that, inlined text/Markdown/code
# (never a native part, unlike PDF/image), must never reach the wire either.
_HUGE_QUERY = "word " * 600_000  # ~500k tokens at the estimator's chars/3


def test_oversized_inlined_text_to_confirmed_model_raises_before_the_wire(monkeypatch):
    with FakeLLMServer([(200, _GROQ_OK_RESPONSE)]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")
        request = _request("groq/openai/gpt-oss-120b", query=_HUGE_QUERY)
        with pytest.raises(ExternalAttachmentTooLargeError) as exc_info:
            asyncio.run(client.generate_response(request, "sk-test"))

    assert exc_info.value.model_name == "groq/openai/gpt-oss-120b"
    assert exc_info.value.budget_tokens == 131072
    assert exc_info.value.estimated_tokens > exc_info.value.budget_tokens
    assert server.requests == []


def test_oversized_inlined_text_streaming_path_is_also_gated(monkeypatch):
    with FakeLLMServer([(200, _GROQ_OK_RESPONSE)]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")
        request = _request("groq/openai/gpt-oss-120b", query=_HUGE_QUERY)

        async def _drain():
            async for _ in client.stream_response(request, "sk-test"):
                pass

        with pytest.raises(ExternalAttachmentTooLargeError):
            asyncio.run(_drain())

    assert server.requests == []


def test_oversized_inlined_text_to_uncatalogued_model_is_not_blocked(monkeypatch):
    """Same conservative bias as the capability gate: a model LiteLLM has no
    catalog entry for is a data gap, not proof the request is too large."""
    with FakeLLMServer([(200, _OK_RESPONSE)]) as server:
        monkeypatch.setenv("OPENAI_API_BASE", f"{server.base_url}/v1")
        client = LiteLLMTransportClient("openai")
        request = _request("openai/some-unmapped-future-model", query=_HUGE_QUERY)
        asyncio.run(client.generate_response(request, "sk-test"))

    assert len(server.requests) == 1


def test_ordinary_size_text_request_is_not_blocked_by_the_budget_check(monkeypatch):
    with FakeLLMServer([(200, _GROQ_OK_RESPONSE)]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")
        request = _request("groq/openai/gpt-oss-120b", query="A normal-sized question about a normal-sized document.")
        asyncio.run(client.generate_response(request, "sk-test"))

    assert len(server.requests) == 1
