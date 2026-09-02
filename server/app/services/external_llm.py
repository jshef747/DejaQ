import logging
from collections.abc import AsyncGenerator

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse, ExternalStreamChunk
from app.services.llm_providers import LLMProviderClient, is_usable_provider, redact_api_key
from app.services.llm_providers.litellm_transport import LiteLLMTransportClient
from app.utils.exceptions import ExternalLLMError

logger = logging.getLogger("dejaq.services.external_llm")

# Every usable provider (see `llm_providers.is_usable_provider`) routes
# through the one LiteLLM transport - no hand-written vendor clients left.
# Built lazily, one `LiteLLMTransportClient` per provider on first use,
# rather than eagerly for a hand-kept set: any single-API-key provider
# LiteLLM serves is usable, not just a fixed six.
_PROVIDER_CLIENTS: dict[str, LLMProviderClient] = {}


class ExternalLLMService:
    @staticmethod
    def _client_for(provider: str) -> LLMProviderClient:
        client = _PROVIDER_CLIENTS.get(provider)
        if client is None:
            if not is_usable_provider(provider):
                logger.error("External LLM provider is not usable: %s", provider)
                raise ExternalLLMError(f"Provider '{provider}' is not wired to a live client.")
            client = LiteLLMTransportClient(provider)
            _PROVIDER_CLIENTS[provider] = client
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
