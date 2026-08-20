"""Migration stages L2-L5: `external_llm._PROVIDER_CLIENTS` switches DejaQ's
live providers, one at a time, onto the LiteLLM transport. Each stage's
routing assertion lives here, added in the same commit as the switch.
"""
import pytest

from app.services import external_llm
from app.services.llm_providers.google import GoogleProviderClient
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from app.services.llm_providers.openai import OpenAIProviderClient

pytestmark = pytest.mark.no_model


def test_deepseek_routes_through_litellm_transport_and_every_other_provider_is_untouched():
    deepseek_client = external_llm._PROVIDER_CLIENTS["deepseek"]
    assert isinstance(deepseek_client, LiteLLMTransportClient)
    assert deepseek_client._provider == "deepseek"

    assert isinstance(external_llm._PROVIDER_CLIENTS["google"], GoogleProviderClient)
    assert isinstance(external_llm._PROVIDER_CLIENTS["xai"], OpenAIProviderClient)
    assert isinstance(external_llm._PROVIDER_CLIENTS["groq"], OpenAIProviderClient)
    assert isinstance(external_llm._PROVIDER_CLIENTS["openai"], OpenAIProviderClient)
