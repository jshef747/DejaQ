import asyncio

import litellm
import pytest

from app.schemas.chat import ExternalLLMRequest
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from tests._fake_llm_server import FakeSSEServer

pytestmark = pytest.mark.no_model


def _request(model: str = "openai/fake-model") -> ExternalLLMRequest:
    return ExternalLLMRequest(
        query="Hello",
        history=[{"role": "assistant", "content": "Hi"}],
        system_prompt="Be useful.",
        model=model,
        max_tokens=64,
    )


def test_streams_incremental_chunks_and_a_terminal_chunk_with_usage(monkeypatch):
    with FakeSSEServer(["Hel", "lo"], final_usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}) as server:
        monkeypatch.setenv("OPENAI_API_BASE", f"{server.base_url}/v1")
        client = LiteLLMTransportClient("openai")

        async def run():
            chunks = [c async for c in client.stream_response(_request(), "sk-test-secret")]
            return chunks

        chunks = asyncio.run(run())

    text_chunks = [c for c in chunks if not c.final]
    assert [c.text for c in text_chunks] == ["Hel", "lo"]

    final = chunks[-1]
    assert final.final is not None
    assert final.final.text == "Hello"
    assert final.final.model_used == "openai/fake-model"
    assert final.final.prompt_tokens == 3
    assert final.final.completion_tokens == 2
    assert final.final.finish_reason == "stop"

    sent = server.requests[0]
    assert sent["stream"] is True
    assert sent["stream_options"] == {"include_usage": True}


def test_stream_is_closed_when_the_consumer_abandons_it(monkeypatch):
    """Twin of the OpenAI-client test of the same name. Wraps LiteLLM's own
    CustomStreamWrapper.aclose to record whether closing the outer generator
    actually released the underlying connection - the leak `aclosing`
    (not `async with`) exists to prevent, since CustomStreamWrapper has
    `aclose` but no `__aenter__`."""
    closed = {"value": False}
    original_aclose = litellm.CustomStreamWrapper.aclose

    async def _wrapped_aclose(self):
        closed["value"] = True
        return await original_aclose(self)

    monkeypatch.setattr(litellm.CustomStreamWrapper, "aclose", _wrapped_aclose)

    with FakeSSEServer(["Hel", "lo", "!"]) as server:
        monkeypatch.setenv("OPENAI_API_BASE", f"{server.base_url}/v1")
        client = LiteLLMTransportClient("openai")

        async def run():
            chunks = client.stream_response(_request(), "sk-test-secret")
            first = await anext(chunks)
            assert first.text == "Hel"
            await chunks.aclose()

        asyncio.run(run())

    assert closed["value"] is True
