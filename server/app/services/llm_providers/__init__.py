from collections.abc import AsyncGenerator
from typing import Protocol

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse, ExternalStreamChunk
from app.services.llm_providers import _litellm_config  # noqa: F401 - side effects only
from app.services.llm_providers.common import redact_api_key
from app.services.llm_providers.provider_keys import is_usable_provider  # noqa: F401 - re-exported


class LLMProviderClient(Protocol):
    async def generate_response(
        self,
        request: ExternalLLMRequest,
        api_key: str,
    ) -> ExternalLLMResponse:
        ...

    def stream_response(
        self,
        request: ExternalLLMRequest,
        api_key: str,
    ) -> AsyncGenerator[ExternalStreamChunk, None]:
        ...
