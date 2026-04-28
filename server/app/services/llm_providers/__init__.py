from typing import Protocol

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse

LIVE_PROVIDERS = {"google", "openai", "anthropic"}


class LLMProviderClient(Protocol):
    async def generate_response(
        self,
        request: ExternalLLMRequest,
        api_key: str,
    ) -> ExternalLLMResponse:
        ...


def redact_api_key(message: object, api_key: str) -> str:
    text = str(message)
    if api_key:
        return text.replace(api_key, "<redacted>")
    return text
