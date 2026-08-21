import asyncio

import pytest

from app.schemas.chat import ExternalLLMRequest
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from app.utils.exceptions import ExternalAttachmentUnsupportedError
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
    return ExternalLLMRequest(
        query="What does this show?",
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
