import logging
import time

import openai

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.services.llm_providers import redact_api_key
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.llm_providers.openai")


class OpenAIProviderClient:
    async def generate_response(self, request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse:
        if not request.query:
            raise ValueError("ExternalLLMRequest.query must not be empty.")

        client = openai.AsyncOpenAI(api_key=api_key)
        messages = [{"role": "system", "content": request.system_prompt}]
        messages.extend(request.history)
        messages.append({"role": "user", "content": request.query})

        logger.debug("Sending hard query to OpenAI model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        try:
            response = await client.chat.completions.create(
                model=request.model,
                messages=messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        except openai.AuthenticationError as exc:
            msg = redact_api_key(exc, api_key)
            logger.error("OpenAI authentication failed: %s", msg)
            raise ExternalLLMAuthError(f"Authentication failed: {msg}") from exc
        except openai.APITimeoutError as exc:
            msg = redact_api_key(exc, api_key)
            logger.error("OpenAI timeout: %s", msg)
            raise ExternalLLMTimeoutError(f"Provider timeout: {msg}") from exc
        except openai.OpenAIError as exc:
            msg = redact_api_key(exc, api_key)
            logger.error("OpenAI API error: %s", msg)
            raise ExternalLLMError(f"Provider error: {msg}") from exc

        latency_ms = (time.perf_counter() - start) * 1000
        usage = response.usage
        content = response.choices[0].message.content or ""
        logger.debug(
            "OpenAI request successful (model=%s, latency=%.2f ms, prompt_tokens=%d, completion_tokens=%d)",
            request.model,
            latency_ms,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )
        return ExternalLLMResponse(
            text=content,
            model_used=request.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
        )
