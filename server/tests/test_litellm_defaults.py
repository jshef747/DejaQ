import asyncio

import litellm
import pytest

from app.services.llm_providers._litellm_config import DEFAULT_CALL_KWARGS
from tests._fake_llm_server import FakeLLMServer

pytestmark = pytest.mark.no_model


def test_default_call_kwargs_makes_exactly_one_request_on_429() -> None:
    """The test that stops a future contributor deleting num_retries=0.

    LiteLLM's acompletion retries 3x by default even though litellm.num_retries
    reads as None. Left alone, a rate-limited request triples provider spend
    and latency and corrupts the latency_ms DejaQ records. A call made with
    DEFAULT_CALL_KWARGS must produce exactly one upstream request.
    """
    responses = [(429, {"error": {"message": "rate limited", "type": "rate_limit_error"}})]

    with FakeLLMServer(responses) as server:
        async def call() -> None:
            try:
                await litellm.acompletion(
                    model="openai/fake-model",
                    api_base=f"{server.base_url}/v1",
                    api_key="sk-test",
                    messages=[{"role": "user", "content": "hi"}],
                    timeout=5,
                    **DEFAULT_CALL_KWARGS,
                )
            except litellm.RateLimitError:
                pass

        asyncio.run(call())

    assert len(server.requests) == 1
