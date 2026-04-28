import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("provider_name", ["google", "openai", "anthropic"])
def test_provider_clients_do_not_log_api_key_on_success(monkeypatch, caplog, provider_name):
    secret = "SecretKey123"

    if provider_name == "google":
        from app.services.llm_providers import google as module

        class FakeModels:
            async def generate_content(self, **kwargs):
                return SimpleNamespace(
                    text="ok",
                    usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1),
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
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
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
                    content=[SimpleNamespace(text="ok")],
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                )

        class FakeClient:
            def __init__(self, api_key):
                self.messages = FakeMessages()

        monkeypatch.setattr(module.anthropic, "AsyncAnthropic", FakeClient)
        client = module.AnthropicProviderClient()

    from app.schemas.chat import ExternalLLMRequest

    request = ExternalLLMRequest(query="Hello", model="provider-model")
    with caplog.at_level("DEBUG"):
        asyncio.run(client.generate_response(request, secret))

    assert secret not in caplog.text


@pytest.mark.parametrize("provider_name", ["google", "openai", "anthropic"])
def test_provider_clients_redact_api_key_on_error(monkeypatch, caplog, provider_name):
    secret = "SecretKey123"

    if provider_name == "google":
        from app.services.llm_providers import google as module

        class FakeAPIError(Exception):
            pass

        class FakeModels:
            async def generate_content(self, **kwargs):
                raise FakeAPIError(f"provider echoed {secret}")

        class FakeClient:
            def __init__(self, api_key):
                self.aio = SimpleNamespace(models=FakeModels())

        monkeypatch.setattr(module.genai, "Client", FakeClient)
        monkeypatch.setattr(module.genai_errors, "APIError", FakeAPIError)
        client = module.GoogleProviderClient()
    elif provider_name == "openai":
        from app.services.llm_providers import openai as module

        class FakeAPIError(Exception):
            pass

        class FakeCompletions:
            async def create(self, **kwargs):
                raise FakeAPIError(f"provider echoed {secret}")

        class FakeClient:
            def __init__(self, api_key):
                self.chat = SimpleNamespace(completions=FakeCompletions())

        monkeypatch.setattr(module.openai, "AsyncOpenAI", FakeClient)
        monkeypatch.setattr(module.openai, "OpenAIError", FakeAPIError)
        client = module.OpenAIProviderClient()
    else:
        from app.services.llm_providers import anthropic as module

        class FakeAPIError(Exception):
            pass

        class FakeMessages:
            async def create(self, **kwargs):
                raise FakeAPIError(f"provider echoed {secret}")

        class FakeClient:
            def __init__(self, api_key):
                self.messages = FakeMessages()

        monkeypatch.setattr(module.anthropic, "AsyncAnthropic", FakeClient)
        monkeypatch.setattr(module.anthropic, "APIError", FakeAPIError)
        client = module.AnthropicProviderClient()

    from app.schemas.chat import ExternalLLMRequest
    from app.utils.exceptions import ExternalLLMError

    request = ExternalLLMRequest(query="Hello", model="provider-model")
    with caplog.at_level("ERROR"), pytest.raises(ExternalLLMError):
        asyncio.run(client.generate_response(request, secret))

    assert secret not in caplog.text
    assert "<redacted>" in caplog.text


def test_external_llm_dispatcher_redacts_api_key_on_error(monkeypatch, caplog):
    from app.schemas.chat import ExternalLLMRequest
    from app.services import external_llm

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
