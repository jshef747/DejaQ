import base64
import logging
import time
from functools import lru_cache

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse
from app.services.llm_providers.common import elapsed_ms, ensure_query, normalize_finish_reason, redact_api_key
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.llm_providers.google")


@lru_cache(maxsize=32)
def _get_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


_client_factory = genai.Client


def _clear_client_cache_if_factory_changed() -> None:
    global _client_factory
    if _client_factory is not genai.Client:
        _get_client.cache_clear()
        _client_factory = genai.Client


class GoogleProviderClient:
    async def generate_response(self, request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse:
        ensure_query(request)

        _clear_client_cache_if_factory_changed()
        client = _get_client(api_key)
        contents: list[types.Content] = []
        for msg in request.history:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
        user_parts = [types.Part(text=request.query)]
        if request.image_b64:
            user_parts.insert(0, types.Part.from_bytes(
                data=base64.b64decode(request.image_b64),
                mime_type=request.image_mime or "image/jpeg",
            ))
        # A PDF is the same call with a different mime type — Gemini parses it natively.
        if request.file_b64:
            user_parts.insert(0, types.Part.from_bytes(
                data=base64.b64decode(request.file_b64),
                mime_type=request.file_mime or "application/pdf",
            ))
        contents.append(types.Content(role="user", parts=user_parts))

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

        latency_ms = elapsed_ms(start)
        usage = response.usage_metadata
        logger.debug(
            "Google request successful (model=%s, latency=%.2f ms, prompt_tokens=%d, completion_tokens=%d)",
            request.model,
            latency_ms,
            usage.prompt_token_count if usage else 0,
            usage.candidates_token_count if usage else 0,
        )
        candidate_finish_reason = (
            response.candidates[0].finish_reason if response.candidates else None
        )
        return ExternalLLMResponse(
            text=response.text or "",
            model_used=request.model,
            prompt_tokens=usage.prompt_token_count if usage else 0,
            completion_tokens=usage.candidates_token_count if usage else 0,
            latency_ms=latency_ms,
            finish_reason=normalize_finish_reason(candidate_finish_reason),
        )
