import asyncio
from types import SimpleNamespace

import pytest

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMTimeoutError


def _request(model: str = "provider-model") -> ExternalLLMRequest:
    return ExternalLLMRequest(
        query="Hello",
        history=[{"role": "assistant", "content": "Hi"}],
        system_prompt="Be useful.",
        model=model,
        max_tokens=64,
        temperature=0.2,
    )


def test_google_provider_client_returns_contract_shape(monkeypatch):
    from app.services.llm_providers import google as google_provider

    class FakeModels:
        async def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="Google answer",
                usage_metadata=SimpleNamespace(prompt_token_count=3, candidates_token_count=4),
                candidates=[SimpleNamespace(finish_reason="STOP")],
            )

    class FakeClient:
        def __init__(self, api_key):
            self.aio = SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(google_provider.genai, "Client", FakeClient)

    response = asyncio.run(
        google_provider.GoogleProviderClient().generate_response(
            _request("gemini-2.5-flash"),
            "SecretKey123",
        )
    )

    assert isinstance(response, ExternalLLMResponse)
    assert response.text == "Google answer"
    assert response.model_used == "gemini-2.5-flash"
    assert response.prompt_tokens == 3
    assert response.completion_tokens == 4
    assert response.finish_reason == "stop"


def test_openai_provider_client_returns_contract_shape(monkeypatch):
    from app.services.llm_providers import openai as openai_provider

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="OpenAI answer"),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=6),
            )

    class FakeClient:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai_provider.openai, "AsyncOpenAI", FakeClient)

    response = asyncio.run(
        openai_provider.OpenAIProviderClient().generate_response(_request("gpt-4o"), "SecretKey123")
    )

    assert isinstance(response, ExternalLLMResponse)
    assert response.text == "OpenAI answer"
    assert response.model_used == "gpt-4o"
    assert response.prompt_tokens == 5
    assert response.completion_tokens == 6
    assert response.finish_reason == "stop"


def test_anthropic_provider_client_returns_contract_shape_and_splits_system(monkeypatch):
    from app.services.llm_providers import anthropic as anthropic_provider

    calls = {}

    class FakeMessages:
        async def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text="Anthropic answer")],
                usage=SimpleNamespace(input_tokens=7, output_tokens=8),
                stop_reason="end_turn",
            )

    class FakeClient:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic_provider.anthropic, "AsyncAnthropic", FakeClient)

    response = asyncio.run(
        anthropic_provider.AnthropicProviderClient().generate_response(
            _request("claude-sonnet-4-5"),
            "SecretKey123",
        )
    )

    assert isinstance(response, ExternalLLMResponse)
    assert response.text == "Anthropic answer"
    assert response.model_used == "claude-sonnet-4-5"
    assert response.prompt_tokens == 7
    assert response.completion_tokens == 8
    assert response.finish_reason == "stop"
    assert calls["system"] == "Be useful."
    assert all(msg["role"] != "system" for msg in calls["messages"])


@pytest.mark.parametrize("provider_name", ["google", "openai", "anthropic"])
def test_provider_clients_report_truncation_as_length(monkeypatch, provider_name):
    """Each provider names 'the token budget cut this off' differently
    (Anthropic max_tokens, OpenAI length, Google MAX_TOKENS) - all three must
    normalize to the same finish_reason="length" so downstream code (the
    /v1/chat/completions and /v1/responses finish_reason/status fields) can
    react to one value regardless of which provider answered."""
    if provider_name == "google":
        from app.services.llm_providers import google as module

        class FakeModels:
            async def generate_content(self, **kwargs):
                return SimpleNamespace(
                    text="cut off",
                    usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1),
                    candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
                )

        class FakeClient:
            def __init__(self, api_key):
                self.aio = SimpleNamespace(models=FakeModels())

        monkeypatch.setattr(module.genai, "Client", FakeClient)
        client = module.GoogleProviderClient()
    elif provider_name == "openai":
        from app.services.llm_providers import openai as module

        class FakeCompletions:
            async def create(self, **kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(
                        message=SimpleNamespace(content="cut off"),
                        finish_reason="length",
                    )],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                )

        class FakeClient:
            def __init__(self, api_key):
                self.chat = SimpleNamespace(completions=FakeCompletions())

        monkeypatch.setattr(module.openai, "AsyncOpenAI", FakeClient)
        client = module.OpenAIProviderClient()
    else:
        from app.services.llm_providers import anthropic as module

        class FakeMessages:
            async def create(self, **kwargs):
                return SimpleNamespace(
                    content=[SimpleNamespace(text="cut off")],
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                    stop_reason="max_tokens",
                )

        class FakeClient:
            def __init__(self, api_key):
                self.messages = FakeMessages()

        monkeypatch.setattr(module.anthropic, "AsyncAnthropic", FakeClient)
        client = module.AnthropicProviderClient()

    response = asyncio.run(client.generate_response(_request(), "SecretKey123"))

    assert response.finish_reason == "length"


@pytest.mark.parametrize("provider_name", ["google", "openai", "anthropic"])
def test_provider_clients_map_auth_errors_uniformly(monkeypatch, provider_name):
    if provider_name == "google":
        from app.services.llm_providers import google as module

        class FakeAuthError(Exception):
            code = 401

        class FakeModels:
            async def generate_content(self, **kwargs):
                raise FakeAuthError("bad secret")

        class FakeClient:
            def __init__(self, api_key):
                self.aio = SimpleNamespace(models=FakeModels())

        monkeypatch.setattr(module.genai, "Client", FakeClient)
        monkeypatch.setattr(module.genai_errors, "ClientError", FakeAuthError)
        client = module.GoogleProviderClient()
    elif provider_name == "openai":
        from app.services.llm_providers import openai as module

        class FakeAuthError(Exception):
            pass

        class FakeCompletions:
            async def create(self, **kwargs):
                raise FakeAuthError("bad secret")

        class FakeClient:
            def __init__(self, api_key):
                self.chat = SimpleNamespace(completions=FakeCompletions())

        monkeypatch.setattr(module.openai, "AsyncOpenAI", FakeClient)
        monkeypatch.setattr(module.openai, "AuthenticationError", FakeAuthError)
        client = module.OpenAIProviderClient()
    else:
        from app.services.llm_providers import anthropic as module

        class FakeAuthError(Exception):
            pass

        class FakeMessages:
            async def create(self, **kwargs):
                raise FakeAuthError("bad secret")

        class FakeClient:
            def __init__(self, api_key):
                self.messages = FakeMessages()

        monkeypatch.setattr(module.anthropic, "AsyncAnthropic", FakeClient)
        monkeypatch.setattr(module.anthropic, "AuthenticationError", FakeAuthError)
        client = module.AnthropicProviderClient()

    with pytest.raises(ExternalLLMAuthError):
        asyncio.run(client.generate_response(_request(), "SecretKey123"))


@pytest.mark.parametrize("provider_name", ["google", "openai", "anthropic"])
def test_provider_clients_map_timeout_errors_uniformly(monkeypatch, provider_name):
    if provider_name == "google":
        from app.services.llm_providers import google as module

        class FakeModels:
            async def generate_content(self, **kwargs):
                raise TimeoutError("slow secret")

        class FakeClient:
            def __init__(self, api_key):
                self.aio = SimpleNamespace(models=FakeModels())

        monkeypatch.setattr(module.genai, "Client", FakeClient)
        client = module.GoogleProviderClient()
    elif provider_name == "openai":
        from app.services.llm_providers import openai as module

        class FakeTimeoutError(Exception):
            pass

        class FakeCompletions:
            async def create(self, **kwargs):
                raise FakeTimeoutError("slow secret")

        class FakeClient:
            def __init__(self, api_key):
                self.chat = SimpleNamespace(completions=FakeCompletions())

        monkeypatch.setattr(module.openai, "AsyncOpenAI", FakeClient)
        monkeypatch.setattr(module.openai, "APITimeoutError", FakeTimeoutError)
        client = module.OpenAIProviderClient()
    else:
        from app.services.llm_providers import anthropic as module

        class FakeTimeoutError(Exception):
            pass

        class FakeMessages:
            async def create(self, **kwargs):
                raise FakeTimeoutError("slow secret")

        class FakeClient:
            def __init__(self, api_key):
                self.messages = FakeMessages()

        monkeypatch.setattr(module.anthropic, "AsyncAnthropic", FakeClient)
        monkeypatch.setattr(module.anthropic, "APITimeoutError", FakeTimeoutError)
        client = module.AnthropicProviderClient()

    with pytest.raises(ExternalLLMTimeoutError):
        asyncio.run(client.generate_response(_request(), "SecretKey123"))


def test_openai_provider_client_sends_reasoning_params_for_o_series(monkeypatch):
    """o1-/o3-/o4- models reject `max_tokens` and non-default `temperature`;
    the client must send `max_completion_tokens` and omit `temperature`."""
    from app.services.llm_providers import openai as openai_provider

    calls = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="o-series answer"),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

    class FakeClient:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai_provider.openai, "AsyncOpenAI", FakeClient)

    response = asyncio.run(
        openai_provider.OpenAIProviderClient().generate_response(_request("o4-mini"), "SecretKey123")
    )

    assert response.text == "o-series answer"
    assert calls["max_completion_tokens"] == 64
    assert "max_tokens" not in calls
    assert "temperature" not in calls


def test_openai_provider_client_sends_legacy_params_for_non_reasoning_models(monkeypatch):
    from app.services.llm_providers import openai as openai_provider

    calls = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="answer"),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

    class FakeClient:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai_provider.openai, "AsyncOpenAI", FakeClient)

    asyncio.run(openai_provider.OpenAIProviderClient().generate_response(_request("gpt-4o"), "SecretKey123"))

    assert calls["max_tokens"] == 64
    assert calls["temperature"] == 0.2
    assert "max_completion_tokens" not in calls


def test_google_provider_client_coalesces_none_token_counts(monkeypatch):
    """Blocked/empty-candidate Gemini responses carry usage_metadata with
    None token counts; the client must not let that crash into a
    Pydantic ValidationError on ExternalLLMResponse.completion_tokens: int."""
    from app.services.llm_providers import google as google_provider

    class FakeModels:
        async def generate_content(self, **kwargs):
            return SimpleNamespace(
                text=None,
                usage_metadata=SimpleNamespace(prompt_token_count=None, candidates_token_count=None),
                candidates=[],
            )

    class FakeClient:
        def __init__(self, api_key):
            self.aio = SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(google_provider.genai, "Client", FakeClient)

    response = asyncio.run(
        google_provider.GoogleProviderClient().generate_response(_request("gemini-2.5-flash"), "SecretKey123")
    )

    assert response.prompt_tokens == 0
    assert response.completion_tokens == 0
    assert response.text == ""


# ── Streaming: the SDK stream is released when the consumer walks away ──
#
# A cloud answer keeps the upstream HTTPS response open for the whole
# generation, and a mid-answer abort (the user hits stop, or navigates away)
# closes these generators where they are suspended. Iterating the SDK stream
# without closing it leaves that connection checked out.


class _FakeSDKStream:
    """Stands in for anthropic/openai `AsyncStream`: an async iterator that is
    also an async context manager, recording whether it was closed."""

    def __init__(self, events):
        self._events = list(events)
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


def test_anthropic_stream_is_closed_when_the_consumer_abandons_it(monkeypatch):
    from app.services.llm_providers import anthropic as anthropic_provider

    stream = _FakeSDKStream([
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text="Hel")),
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text="lo")),
    ])

    class FakeMessages:
        async def create(self, **kwargs):
            return stream

    class FakeClient:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic_provider.anthropic, "AsyncAnthropic", FakeClient)

    async def run():
        chunks = anthropic_provider.AnthropicProviderClient().stream_response(
            _request("claude-sonnet-4-6"), "SecretKey123"
        )
        assert (await anext(chunks)).text == "Hel"
        await chunks.aclose()
        assert stream.closed is True

    asyncio.run(run())


def test_openai_stream_is_closed_when_the_consumer_abandons_it(monkeypatch):
    from app.services.llm_providers import openai as openai_provider

    def _chunk(content: str):
        return SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(finish_reason=None, delta=SimpleNamespace(content=content))],
        )

    stream = _FakeSDKStream([_chunk("Hel"), _chunk("lo")])

    class FakeCompletions:
        async def create(self, **kwargs):
            return stream

    class FakeClient:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai_provider.openai, "AsyncOpenAI", FakeClient)

    async def run():
        chunks = openai_provider.OpenAIProviderClient().stream_response(
            _request("gpt-4o"), "SecretKey123"
        )
        assert (await anext(chunks)).text == "Hel"
        await chunks.aclose()
        assert stream.closed is True

    asyncio.run(run())


def test_google_stream_is_closed_when_the_consumer_abandons_it(monkeypatch):
    """google-genai hands back a plain async generator rather than a context
    manager, so it is closed explicitly instead - left to the event loop's
    asyncgen finalizer the connection outlives the request."""
    from app.services.llm_providers import google as google_provider

    closed = {"value": False}

    async def fake_stream():
        try:
            for piece in ("Hel", "lo"):
                yield SimpleNamespace(text=piece, usage_metadata=None, candidates=None)
        finally:
            closed["value"] = True

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            return fake_stream()

    class FakeClient:
        def __init__(self, api_key):
            self.aio = SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(google_provider.genai, "Client", FakeClient)

    async def run():
        chunks = google_provider.GoogleProviderClient().stream_response(
            _request("gemini-2.5-flash"), "SecretKey123"
        )
        assert (await anext(chunks)).text == "Hel"
        await chunks.aclose()
        assert closed["value"] is True

    asyncio.run(run())
