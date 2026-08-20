"""L4: anthropic routes through LiteLLM - the first stage where a genuinely
different wire shape (Anthropic Messages, not OpenAI chat completions) is
translated by LiteLLM rather than by DejaQ's own hand-written client.
"""
import asyncio

import pytest

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.services.external_llm import ExternalLLMService
from tests._fake_llm_server import FakeLLMServer

pytestmark = pytest.mark.no_model


def _request(
    model: str = "claude-sonnet-4-5",
    *,
    temperature: float | None = 0.2,
    image_b64: str | None = None,
    image_mime: str | None = None,
    file_b64: str | None = None,
    file_mime: str | None = None,
    file_name: str | None = None,
) -> ExternalLLMRequest:
    return ExternalLLMRequest(
        query="Hello",
        history=[{"role": "assistant", "content": "Hi"}],
        system_prompt="Be useful.",
        model=model,
        max_tokens=64,
        temperature=temperature,
        image_b64=image_b64,
        image_mime=image_mime,
        file_b64=file_b64,
        file_mime=file_mime,
        file_name=file_name,
    )


def _ok_anthropic_response(text: str = "Anthropic answer", *, prompt_tokens: int = 7, completion_tokens: int = 8) -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-sonnet-4-5", "stop_reason": "end_turn",
        "usage": {"input_tokens": prompt_tokens, "output_tokens": completion_tokens},
    }


def _call(server: FakeLLMServer, request: ExternalLLMRequest, monkeypatch) -> ExternalLLMResponse:
    monkeypatch.setenv("ANTHROPIC_API_BASE", server.base_url)
    return asyncio.run(ExternalLLMService().generate_response(request, "anthropic", "sk-ant-test"))


def test_anthropic_provider_client_returns_contract_shape_and_splits_system_through_litellm(monkeypatch):
    """Ported: test_anthropic_provider_client_returns_contract_shape_and_
    splits_system's assertions must still hold now that anthropic is routed
    through LiteLLM instead of the hand-written client."""
    with FakeLLMServer([(200, _ok_anthropic_response())]) as server:
        response = _call(server, _request("claude-sonnet-4-5"), monkeypatch)

    assert isinstance(response, ExternalLLMResponse)
    assert response.text == "Anthropic answer"
    assert response.model_used == "claude-sonnet-4-5"
    assert response.prompt_tokens == 7
    assert response.completion_tokens == 8
    assert response.finish_reason == "stop"

    sent = server.requests[0]
    assert sent["system"] == [{"type": "text", "text": "Be useful."}]
    assert all(msg["role"] != "system" for msg in sent["messages"])


def test_image_url_part_becomes_an_anthropic_image_block(monkeypatch):
    with FakeLLMServer([(200, _ok_anthropic_response())]) as server:
        _call(server, _request(image_b64="aGVsbG8=", image_mime="image/png"), monkeypatch)

    content = server.requests[0]["messages"][-1]["content"]
    image_parts = [part for part in content if part.get("type") == "image"]
    assert len(image_parts) == 1
    assert image_parts[0]["source"] == {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}


def test_file_part_becomes_an_anthropic_document_block(monkeypatch):
    with FakeLLMServer([(200, _ok_anthropic_response())]) as server:
        _call(
            server,
            _request(file_b64="aGVsbG8=", file_mime="application/pdf", file_name="doc.pdf"),
            monkeypatch,
        )

    content = server.requests[0]["messages"][-1]["content"]
    doc_parts = [part for part in content if part.get("type") == "document"]
    assert len(doc_parts) == 1
    assert doc_parts[0]["source"] == {"type": "base64", "media_type": "application/pdf", "data": "aGVsbG8="}


def test_dejaq_temperature_deprecated_claude_sonnet_5_drops_temperature_on_the_wire(monkeypatch):
    """Closes dejaq-temperature-deprecated. claude-sonnet-5 carries
    supports_sampling_params: false in LiteLLM's model table, so drop_params
    strips a caller-supplied temperature before it reaches the wire - no
    hand-written per-model carve-out needed, one design instead of two."""
    with FakeLLMServer([(200, _ok_anthropic_response())]) as server:
        _call(server, _request("claude-sonnet-5", temperature=0.7), monkeypatch)

    assert "temperature" not in server.requests[0]
