import logging
from collections.abc import AsyncGenerator

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse, ExternalStreamChunk
from app.services import provider_registry
from app.services.llm_providers import LLMProviderClient, redact_api_key
from app.services.llm_providers.anthropic import AnthropicProviderClient
from app.services.llm_providers.google import GoogleProviderClient
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from app.services.llm_providers.openai import OpenAIProviderClient
from app.utils.exceptions import ExternalLLMError

logger = logging.getLogger("dejaq.services.external_llm")

# Every live provider speaking the OpenAI chat-completions wire shape shares
# one client class; only the host differs, and that host comes from the
# registry's own row rather than being hardcoded per provider here.
# Providers migrated onto the LiteLLM transport (migration stages L2-L5) are
# listed explicitly below, overriding their entry from the comprehension.
_PROVIDER_CLIENTS: dict[str, LLMProviderClient] = {
    "google": GoogleProviderClient(),
    "anthropic": AnthropicProviderClient(),
    **{
        key: OpenAIProviderClient(base_url=spec.base_url)
        for key, spec in provider_registry.PROVIDERS.items()
        if spec.live and spec.client_shape == provider_registry.ClientShape.OPENAI_CHAT_COMPLETIONS
    },
    "deepseek": LiteLLMTransportClient("deepseek"),
}


class ExternalLLMService:
    @staticmethod
    def _client_for(provider: str) -> LLMProviderClient:
        client = _PROVIDER_CLIENTS.get(provider)
        if client is None:
            logger.error("External LLM provider is not wired: %s", provider)
            raise ExternalLLMError(f"Provider '{provider}' is not wired to a live client.")
        return client

    async def generate_response(
        self,
        request: ExternalLLMRequest,
        provider: str,
        api_key: str,
    ) -> ExternalLLMResponse:
        client = self._client_for(provider)

        logger.debug("Dispatching external LLM request provider=%s model=%s", provider, request.model)
        try:
            return await client.generate_response(request, api_key)
        except Exception as exc:
            logger.debug(
                "External LLM provider failed provider=%s error=%s",
                provider,
                redact_api_key(exc, api_key),
            )
            raise

    async def stream_response(
        self,
        request: ExternalLLMRequest,
        provider: str,
        api_key: str,
    ) -> AsyncGenerator[ExternalStreamChunk, None]:
        """Streaming twin of `generate_response`; same dispatch, same redaction."""
        client = self._client_for(provider)

        logger.debug("Streaming external LLM request provider=%s model=%s", provider, request.model)
        try:
            async for chunk in client.stream_response(request, api_key):
                yield chunk
        except Exception as exc:
            logger.debug(
                "External LLM provider failed provider=%s error=%s",
                provider,
                redact_api_key(exc, api_key),
            )
            raise
