import logging
import time

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.services.llm_providers import redact_api_key
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.llm_providers.google")


class GoogleProviderClient:
    async def generate_response(self, request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse:
        if not request.query:
            raise ValueError("ExternalLLMRequest.query must not be empty.")

        client = genai.Client(api_key=api_key)
        contents: list[types.Content] = []
        for msg in request.history:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=request.query)]))

        config = types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            max_output_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        logger.debug("Sending hard query to Google model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        try:
            response = await client.aio.models.generate_content(
                model=request.model,
                contents=contents,
                config=config,
            )
        except genai_errors.ClientError as exc:
            msg = redact_api_key(exc, api_key)
            if exc.code == 401:
                logger.error("Google authentication failed: %s", msg)
                raise ExternalLLMAuthError(f"Authentication failed: {msg}") from exc
            logger.error("Google client error (code=%d): %s", exc.code, msg)
            raise ExternalLLMError(f"Provider error: {msg}") from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            msg = redact_api_key(exc, api_key)
            logger.error("Google timeout: %s", msg)
            raise ExternalLLMTimeoutError(f"Provider timeout: {msg}") from exc
        except genai_errors.APIError as exc:
            msg = redact_api_key(exc, api_key)
            logger.error("Google API error: %s", msg)
            raise ExternalLLMError(f"Provider error: {msg}") from exc

        latency_ms = (time.perf_counter() - start) * 1000
        usage = response.usage_metadata
        logger.debug(
            "Google request successful (model=%s, latency=%.2f ms, prompt_tokens=%d, completion_tokens=%d)",
            request.model,
            latency_ms,
            usage.prompt_token_count if usage else 0,
            usage.candidates_token_count if usage else 0,
        )
        return ExternalLLMResponse(
            text=response.text or "",
            model_used=request.model,
            prompt_tokens=usage.prompt_token_count if usage else 0,
            completion_tokens=usage.candidates_token_count if usage else 0,
            latency_ms=latency_ms,
        )
