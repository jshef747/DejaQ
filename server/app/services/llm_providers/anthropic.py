import logging
import time

import anthropic

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.services.llm_providers import redact_api_key
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.llm_providers.anthropic")


class AnthropicProviderClient:
    async def generate_response(self, request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse:
        if not request.query:
            raise ValueError("ExternalLLMRequest.query must not be empty.")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        messages = [msg for msg in request.history if msg["role"] in {"user", "assistant"}]
        messages.append({"role": "user", "content": request.query})

        logger.debug("Sending hard query to Anthropic model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        try:
            response = await client.messages.create(
                model=request.model,
                system=request.system_prompt,
                messages=messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        except anthropic.AuthenticationError as exc:
            msg = redact_api_key(exc, api_key)
            logger.error("Anthropic authentication failed: %s", msg)
            raise ExternalLLMAuthError(f"Authentication failed: {msg}") from exc
        except anthropic.APITimeoutError as exc:
            msg = redact_api_key(exc, api_key)
            logger.error("Anthropic timeout: %s", msg)
            raise ExternalLLMTimeoutError(f"Provider timeout: {msg}") from exc
        except anthropic.APIError as exc:
            msg = redact_api_key(exc, api_key)
            logger.error("Anthropic API error: %s", msg)
            raise ExternalLLMError(f"Provider error: {msg}") from exc

        latency_ms = (time.perf_counter() - start) * 1000
        text = response.content[0].text if response.content else ""
        logger.debug(
            "Anthropic request successful (model=%s, latency=%.2f ms, prompt_tokens=%d, completion_tokens=%d)",
            request.model,
            latency_ms,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return ExternalLLMResponse(
            text=text,
            model_used=request.model,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
        )
