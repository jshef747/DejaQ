import contextlib
import logging
import time
from collections.abc import AsyncGenerator, Iterator
from functools import lru_cache

import openai

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse, ExternalStreamChunk
from app.services.llm_providers.common import elapsed_ms, ensure_query, normalize_finish_reason, redact_api_key
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.llm_providers.openai")


@lru_cache(maxsize=32)
def _get_client(api_key: str) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(api_key=api_key)


_client_factory = openai.AsyncOpenAI


def _clear_client_cache_if_factory_changed() -> None:
    global _client_factory
    if _client_factory is not openai.AsyncOpenAI:
        _get_client.cache_clear()
        _client_factory = openai.AsyncOpenAI


@contextlib.contextmanager
def _mapped_errors(api_key: str) -> Iterator[None]:
    """Translate the provider SDK's exceptions into DejaQ's own.

    Shared by the buffered and the streaming call so a new failure mode never
    reaches one path and not the other.
    """
    try:
        yield
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


class OpenAIProviderClient:
    @staticmethod
    def _build_call(request: ExternalLLMRequest) -> tuple[list[dict], dict]:
        messages = [{"role": "system", "content": request.system_prompt}]
        messages.extend(request.history)
        if request.image_b64:
            user_content = [
                {"type": "text", "text": request.query},
                {"type": "image_url", "image_url": {
                    "url": f"data:{request.image_mime or 'image/jpeg'};base64,{request.image_b64}"
                }},
            ]
        elif request.file_b64:
            # Chat Completions takes a PDF as an `file` part carrying a data URL.
            # A `file_id` from the Files API would avoid re-uploading the same
            # document every turn, but that needs an upload+lifecycle of its own;
            # inline is correct while requests stay one-shot and under the size cap.
            user_content = [
                {"type": "text", "text": request.query},
                {"type": "file", "file": {
                    "filename": request.file_name or "document.pdf",
                    "file_data": f"data:{request.file_mime or 'application/pdf'};base64,{request.file_b64}",
                }},
            ]
        else:
            user_content = request.query
        messages.append({"role": "user", "content": user_content})

        # o-series reasoning models (o1-, o3-, o4-) reject `max_tokens` (need
        # `max_completion_tokens`) and any non-default temperature.
        is_reasoning_model = request.model.strip().lower().startswith(("o1-", "o3-", "o4-"))
        extra_kwargs = {"max_completion_tokens": request.max_tokens} if is_reasoning_model else {
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        return messages, extra_kwargs

    async def generate_response(self, request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse:
        ensure_query(request)

        _clear_client_cache_if_factory_changed()
        client = _get_client(api_key)
        messages, extra_kwargs = self._build_call(request)

        logger.debug("Sending hard query to OpenAI model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        with _mapped_errors(api_key):
            response = await client.chat.completions.create(
                model=request.model,
                messages=messages,
                **extra_kwargs,
            )

        latency_ms = elapsed_ms(start)
        usage = response.usage
        choice = response.choices[0]
        content = choice.message.content or ""
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
            finish_reason=normalize_finish_reason(choice.finish_reason),
        )

    async def stream_response(
        self, request: ExternalLLMRequest, api_key: str
    ) -> AsyncGenerator[ExternalStreamChunk, None]:
        """Streaming twin of `generate_response`.

        `stream_options={"include_usage": True}` is what keeps the usage block
        honest: without it a streamed response reports no token counts at all
        and DejaQ would fall back to the word-count estimate.
        """
        ensure_query(request)

        _clear_client_cache_if_factory_changed()
        client = _get_client(api_key)
        messages, extra_kwargs = self._build_call(request)

        logger.debug("Streaming hard query to OpenAI model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        text = ""
        prompt_tokens = completion_tokens = 0
        finish_reason = None
        with _mapped_errors(api_key):
            stream = await client.chat.completions.create(
                model=request.model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                **extra_kwargs,
            )
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage:
                    prompt_tokens = usage.prompt_tokens or prompt_tokens
                    completion_tokens = usage.completion_tokens or completion_tokens
                # The usage-only chunk carries no choices at all.
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                piece = (choice.delta.content if choice.delta else None) or ""
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
