from typing import Protocol

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.services.llm_providers.common import redact_api_key

LIVE_PROVIDERS = {"google", "openai", "anthropic"}


class LLMProviderClient(Protocol):
    async def generate_response(
        self,
        request: ExternalLLMRequest,
        api_key: str,
    ) -> ExternalLLMResponse:
        ...
