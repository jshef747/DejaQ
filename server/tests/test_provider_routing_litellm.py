"""Migration stages L2-L5: `external_llm._PROVIDER_CLIENTS` switches DejaQ's
live providers, one at a time, onto the LiteLLM transport. Each stage's
routing assertion lives here, added in the same commit as the switch.
"""
import asyncio

import pytest

from app.schemas.chat import ExternalLLMRequest
from app.services import external_llm
from app.services.llm_providers.google import GoogleProviderClient
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from app.services.llm_providers.openai import OpenAIProviderClient
from tests._fake_llm_server import FakeLLMServer

pytestmark = pytest.mark.no_model


def test_deepseek_routes_through_litellm_transport_and_every_other_provider_is_untouched():
    deepseek_client = external_llm._PROVIDER_CLIENTS["deepseek"]
    assert isinstance(deepseek_client, LiteLLMTransportClient)
    assert deepseek_client._provider == "deepseek"

    assert isinstance(external_llm._PROVIDER_CLIENTS["google"], GoogleProviderClient)
    assert isinstance(external_llm._PROVIDER_CLIENTS["openai"], OpenAIProviderClient)


def test_xai_and_groq_route_through_litellm_transport():
    xai_client = external_llm._PROVIDER_CLIENTS["xai"]
    groq_client = external_llm._PROVIDER_CLIENTS["groq"]
    assert isinstance(xai_client, LiteLLMTransportClient) and xai_client._provider == "xai"
    assert isinstance(groq_client, LiteLLMTransportClient) and groq_client._provider == "groq"


def _ok_groq_response(content: str = "Groq answer") -> dict:
    return {
        "id": "resp-1", "object": "chat.completion", "created": 1, "model": "qwen/qwen3.6-27b",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
        # Groq's own extension of the OpenAI shape - its response transformer
        # reads this field unconditionally.
        "service_tier": "default",
    }


def test_groq_vision_model_attachment_reaches_the_wire_through_litellm(monkeypatch):
    """Groq serves both vision-capable and text-only models; qwen/qwen3.6-27b
    is the vision one (provider_registry.py). The image part must survive
    routing through the transport unchanged - groq speaks the same
    OpenAI-shaped wire format DejaQ already builds, no translation needed."""
    request = ExternalLLMRequest(
        query="describe this",
        history=[],
        system_prompt="Be useful.",
        model="qwen/qwen3.6-27b",
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
