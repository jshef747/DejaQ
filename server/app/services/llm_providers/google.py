import base64
import contextlib
import logging
import time
from collections.abc import AsyncGenerator, Iterator
from functools import lru_cache

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse, ExternalStreamChunk
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


@contextlib.contextmanager
def _mapped_errors(api_key: str) -> Iterator[None]:
    """Translate the provider SDK's exceptions into DejaQ's own.

    Shared by the buffered and the streaming call so a new failure mode never
    reaches one path and not the other.
    """
    try:
        yield
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


class GoogleProviderClient:
    @staticmethod
    def _build_call(request: ExternalLLMRequest) -> tuple[list[types.Content], types.GenerateContentConfig]:
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

        return contents, config

    async def generate_response(self, request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse:
        ensure_query(request)

        _clear_client_cache_if_factory_changed()
        client = _get_client(api_key)
        contents, config = self._build_call(request)

        logger.debug("Sending hard query to Google model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        with _mapped_errors(api_key):
            response = await client.aio.models.generate_content(
                model=request.model,
                contents=contents,
                config=config,
            )

        latency_ms = elapsed_ms(start)
        usage = response.usage_metadata
        prompt_tokens = (usage.prompt_token_count or 0) if usage else 0
        completion_tokens = (usage.candidates_token_count or 0) if usage else 0
        logger.debug(
            "Google request successful (model=%s, latency=%.2f ms, prompt_tokens=%d, completion_tokens=%d)",
            request.model,
            latency_ms,
            prompt_tokens,
            completion_tokens,
        )
        candidate_finish_reason = (
            response.candidates[0].finish_reason if response.candidates else None
        )
        return ExternalLLMResponse(
            text=response.text or "",
            model_used=request.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            finish_reason=normalize_finish_reason(candidate_finish_reason),
        )

    async def stream_response(
        self, request: ExternalLLMRequest, api_key: str
    ) -> AsyncGenerator[ExternalStreamChunk, None]:
        """Streaming twin of `generate_response`.

        Usage counts and the finish reason only settle on the last chunk, so
        they ride out on the terminal `ExternalStreamChunk.final` rather than
        being guessed from a partial response.
        """
        ensure_query(request)

        _clear_client_cache_if_factory_changed()
        client = _get_client(api_key)
        contents, config = self._build_call(request)

        logger.debug("Streaming hard query to Google model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        text = ""
        prompt_tokens = completion_tokens = 0
        finish_reason = None
        with _mapped_errors(api_key):
            stream = await client.aio.models.generate_content_stream(
                model=request.model,
                contents=contents,
                config=config,
            )
            async for chunk in stream:
                usage = getattr(chunk, "usage_metadata", None)
                if usage:
                    prompt_tokens = usage.prompt_token_count or prompt_tokens
                    completion_tokens = usage.candidates_token_count or completion_tokens
                candidates = getattr(chunk, "candidates", None)
                if candidates and candidates[0].finish_reason:
                    finish_reason = candidates[0].finish_reason
                piece = chunk.text or ""
                if piece:
                    text += piece
                    yield ExternalStreamChunk(text=piece)

        yield ExternalStreamChunk(final=ExternalLLMResponse(
            text=text,
            model_used=request.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=elapsed_ms(start),
            finish_reason=normalize_finish_reason(finish_reason),
        ))
