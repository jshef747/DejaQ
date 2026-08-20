"""Regression for the double-prefix bug (captain-reported, live Groq key):
`litellm_transport.py` used to build `model = f"{_litellm_key(provider)}/{request.model}"`
even though `request.model` is already provider-qualified as stored in the
DB (stage A2's migration qualified every row; stage A1a's write-time
validation rejects an unqualified name). That built a double prefix LiteLLM
only strips one layer of, so the vendor received a still-prefixed, wrong
model id - e.g. Groq got `groq/openai/gpt-oss-120b` instead of
`openai/gpt-oss-120b` and rejected it as unknown.

Every existing transport test constructed its `ExternalLLMRequest` with a
model name passed directly to the transport, so the double prefix never
happened in a test - that gap, not just the missing fix, is what this file
closes. Each case below starts from a stored, qualified model name (the
same string `llm_config_service` would have written to `external_model`)
and asserts the EXACT model string that reaches the wire.
"""
import asyncio

import pytest

from app.schemas.chat import ExternalLLMRequest
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from tests._fake_llm_server import FakeLLMServer, FakeSSEServer

pytestmark = pytest.mark.no_model


def _request(model: str) -> ExternalLLMRequest:
    return ExternalLLMRequest(
        query="Hello",
        history=[],
        system_prompt="Be useful.",
        model=model,
        max_tokens=32,
    )


def _openai_shaped_response(model_echo: str) -> dict:
    return {
        "id": "resp-1", "object": "chat.completion", "created": 1, "model": model_echo,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _groq_shaped_response(model_echo: str) -> dict:
    # Groq's own extension of the OpenAI shape - its response transformer
    # reads this field unconditionally.
    return {**_openai_shaped_response(model_echo), "service_tier": "default"}


def test_groq_stored_qualified_model_with_internal_slash_reaches_wire_unprefixed(monkeypatch):
    """The case that actually surfaced this in production: Groq's own model
    id already contains a slash (`openai/gpt-oss-120b`), so the double
    prefix produced a *third* segment (`groq/groq/openai/gpt-oss-120b`)
    that LiteLLM's single strip left as `groq/openai/gpt-oss-120b` on the
    wire - exactly the id Groq rejected as not found."""
    with FakeLLMServer([(200, _groq_shaped_response("groq/openai/gpt-oss-120b"))]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")
        asyncio.run(client.generate_response(_request("groq/openai/gpt-oss-120b"), "sk-groq-test"))

    assert server.requests[0]["model"] == "openai/gpt-oss-120b"


def test_gemini_stored_qualified_model_reaches_wire_unprefixed(monkeypatch):
    """DejaQ's provider key ('google') differs from LiteLLM's ('gemini'); a
    re-derived prefix would build 'google/gemini/...', which LiteLLM cannot
    resolve at all - Gemini puts the model in the URL path, not the body."""
    body = {
        "candidates": [{"content": {"parts": [{"text": "ok"}], "role": "model"}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    }
    with FakeLLMServer([(200, body)]) as server:
        monkeypatch.setenv("GEMINI_API_BASE", server.base_url)
        client = LiteLLMTransportClient("google")
        asyncio.run(client.generate_response(_request("gemini/gemini-2.5-flash"), "sk-test-secret"))

    assert "models/gemini-2.5-flash" in server.paths[0]
    assert "gemini/gemini-2.5-flash" not in server.paths[0]


def test_anthropic_stored_qualified_model_reaches_wire_unprefixed(monkeypatch):
    body = {
        "id": "msg_1", "type": "message", "role": "assistant",
        "content": [{"type": "text", "text": "ok"}],
        "model": "claude-sonnet-5", "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    with FakeLLMServer([(200, body)]) as server:
        monkeypatch.setenv("ANTHROPIC_API_BASE", server.base_url)
        client = LiteLLMTransportClient("anthropic")
        asyncio.run(client.generate_response(_request("anthropic/claude-sonnet-5"), "sk-ant-test"))

    assert server.requests[0]["model"] == "claude-sonnet-5"


def test_xai_stored_qualified_model_reaches_wire_unprefixed(monkeypatch):
    with FakeLLMServer([(200, _openai_shaped_response("grok-4.6"))]) as server:
        monkeypatch.setenv("XAI_API_BASE", server.base_url)
        client = LiteLLMTransportClient("xai")
        asyncio.run(client.generate_response(_request("xai/grok-4.6"), "sk-xai-test"))

    assert server.requests[0]["model"] == "grok-4.6"


def test_groq_streaming_path_has_the_same_fix(monkeypatch):
    """The streaming twin builds its model string the same way as
    generate_response - must not regress independently."""
    with FakeSSEServer(["ok"]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        client = LiteLLMTransportClient("groq")

        async def run():
            return [c async for c in client.stream_response(_request("groq/openai/gpt-oss-120b"), "sk-groq-test")]

        asyncio.run(run())

    assert server.requests[0]["model"] == "openai/gpt-oss-120b"
