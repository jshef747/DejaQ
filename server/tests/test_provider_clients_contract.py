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


def test_openai_provider_client_returns_contract_shape(monkeypatch):
    from app.services.llm_providers import openai as openai_provider

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="OpenAI answer"))],
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


def test_anthropic_provider_client_returns_contract_shape_and_splits_system(monkeypatch):
    from app.services.llm_providers import anthropic as anthropic_provider

    calls = {}

    class FakeMessages:
        async def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text="Anthropic answer")],
                usage=SimpleNamespace(input_tokens=7, output_tokens=8),
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
    assert calls["system"] == "Be useful."
    assert all(msg["role"] != "system" for msg in calls["messages"])


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
