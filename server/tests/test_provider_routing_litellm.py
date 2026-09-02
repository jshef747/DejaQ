"""Any single-API-key provider LiteLLM serves is usable end to end - see
`llm_providers.is_usable_provider` and `external_llm._client_for`'s lazy,
per-provider client cache. Structured-credential providers (Bedrock/Azure)
stay rejected.
"""
import asyncio

import pytest

from app.schemas.chat import ExternalLLMRequest
from app.services import external_llm
from app.services.llm_providers import is_usable_provider
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from app.utils.exceptions import ExternalLLMError
from tests._fake_llm_server import FakeLLMServer

pytestmark = pytest.mark.no_model


@pytest.mark.parametrize("provider", ["google", "openai", "anthropic", "xai", "deepseek", "groq", "mistral"])
def test_usable_providers_route_through_litellm_transport(provider):
    assert is_usable_provider(provider)
    client = external_llm.ExternalLLMService._client_for(provider)
    assert isinstance(client, LiteLLMTransportClient)
    assert client._provider == provider


def test_client_for_a_provider_is_cached_across_calls():
    first = external_llm.ExternalLLMService._client_for("mistral")
    second = external_llm.ExternalLLMService._client_for("mistral")
    assert first is second


def test_the_three_renamed_providers_are_usable():
    for provider in ("google", "together", "fireworks"):
        assert is_usable_provider(provider)


def test_structured_credential_provider_is_rejected():
    assert not is_usable_provider("azure")
    with pytest.raises(ExternalLLMError):
        external_llm.ExternalLLMService._client_for("azure")


def test_unknown_provider_key_is_rejected():
    assert not is_usable_provider("not-a-real-provider")
    with pytest.raises(ExternalLLMError):
        external_llm.ExternalLLMService._client_for("not-a-real-provider")


def _ok_groq_response(content: str = "Groq answer") -> dict:
    return {
        "id": "resp-1", "object": "chat.completion", "created": 1, "model": "qwen/qwen3.6-27b",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
        # Groq's own extension of the OpenAI shape - its response transformer
        # reads this field unconditionally.
        "service_tier": "default",
    }


def test_external_llm_dispatcher_redacts_api_key_on_error(monkeypatch, caplog):
    """Moved from test_provider_clients_logging.py (deleted, migration stage
    L6): this tests external_llm.py's own dispatcher wrapper, not any of the
    deleted vendor clients, so it survives unchanged."""
    secret = "SecretKey123"

    class FakeClient:
        async def generate_response(self, request, api_key):
            raise RuntimeError(f"provider echoed {secret}")

    monkeypatch.setitem(external_llm._PROVIDER_CLIENTS, "fake", FakeClient())

    request = ExternalLLMRequest(query="Hello", model="provider-model")
    with caplog.at_level("DEBUG"), pytest.raises(RuntimeError):
        asyncio.run(external_llm.ExternalLLMService().generate_response(request, "fake", secret))

    assert secret not in caplog.text
    assert "<redacted>" in caplog.text


def test_groq_vision_model_attachment_reaches_the_wire_through_litellm(monkeypatch):
    """Groq serves both vision-capable and text-only models; qwen/qwen3.6-27b
    is the vision one. The image part must survive routing through the
    transport unchanged - groq speaks the same OpenAI-shaped wire format
    DejaQ already builds, no translation needed."""
    request = ExternalLLMRequest(
        query="describe this",
        history=[],
        system_prompt="Be useful.",
        model="groq/qwen/qwen3.6-27b",
        max_tokens=64,
        image_b64="aGVsbG8=",
        image_mime="image/png",
    )
    with FakeLLMServer([(200, _ok_groq_response())]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        response = asyncio.run(
            external_llm.ExternalLLMService().generate_response(request, "groq", "sk-groq-test")
        )

    assert response.text == "Groq answer"
    user_content = server.requests[0]["messages"][-1]["content"]
    image_parts = [part for part in user_content if part.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="


def test_groq_requests_hidden_reasoning_format_so_think_tags_dont_leak(monkeypatch):
    """Groq's qwen3.6-27b emits <think> tags unless reasoning_format is set.
    LiteLLM has no first-class param for it, so it must reach the wire via
    extra_body - confirmed here rather than assumed."""
    request = ExternalLLMRequest(query="hi", model="groq/qwen/qwen3.6-27b", max_tokens=64)
    with FakeLLMServer([(200, _ok_groq_response())]) as server:
        monkeypatch.setenv("GROQ_API_BASE", server.base_url)
        asyncio.run(external_llm.ExternalLLMService().generate_response(request, "groq", "sk-groq-test"))

    assert server.requests[0]["reasoning_format"] == "hidden"


def test_non_groq_provider_does_not_get_reasoning_format(monkeypatch):
    request = ExternalLLMRequest(query="hi", model="openai/fake-model", max_tokens=64)
    with FakeLLMServer([(200, _ok_groq_response())]) as server:
        monkeypatch.setenv("OPENAI_API_BASE", f"{server.base_url}/v1")
        asyncio.run(external_llm.ExternalLLMService().generate_response(request, "openai", "sk-test"))

    assert "reasoning_format" not in server.requests[0]
