import contextlib
import logging
import time
from collections.abc import AsyncGenerator, Iterator
from functools import lru_cache

import anthropic

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse, ExternalStreamChunk
from app.services.llm_providers.common import elapsed_ms, ensure_query, normalize_finish_reason, redact_api_key
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.llm_providers.anthropic")


@lru_cache(maxsize=32)
def _get_client(api_key: str) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=api_key)


_client_factory = anthropic.AsyncAnthropic


def _clear_client_cache_if_factory_changed() -> None:
    global _client_factory
    if _client_factory is not anthropic.AsyncAnthropic:
        _get_client.cache_clear()
        _client_factory = anthropic.AsyncAnthropic


@contextlib.contextmanager
def _mapped_errors(api_key: str) -> Iterator[None]:
    """Translate the provider SDK's exceptions into DejaQ's own.

    Shared by the buffered and the streaming call so a new failure mode never
    reaches one path and not the other.
    """
    try:
        yield
    except anthropic.AuthenticationError as exc:
        msg = redact_api_key(exc, api_key)
        logger.error("Anthropic authentication failed: %s", msg)
        raise ExternalLLMAuthError(f"Authentication failed: {msg}", status_code=401) from exc
    except anthropic.APITimeoutError as exc:
        msg = redact_api_key(exc, api_key)
        logger.error("Anthropic timeout: %s", msg)
        raise ExternalLLMTimeoutError(f"Provider timeout: {msg}") from exc
    except anthropic.APIError as exc:
        msg = redact_api_key(exc, api_key)
        logger.error("Anthropic API error: %s", msg)
        raise ExternalLLMError(
            f"Provider error: {msg}", status_code=getattr(exc, "status_code", None)
        ) from exc


async def _create_with_temperature_retry(client, request: ExternalLLMRequest, **kwargs):
    """Sends `temperature` only if the caller asked for one, and retries once
    without it if the vendor rejects it by name.

    Anthropic 400s on any non-default temperature for Claude Opus 4.7+ and
    Sonnet 5 (migration guide) - a model can start rejecting it after a vendor
    change, so this degrades to a logged warning instead of an outage.
    """
    if request.temperature is not None:
        try:
            return await client.messages.create(**kwargs, temperature=request.temperature)
        except anthropic.BadRequestError as exc:
            if "temperature" not in str(exc).lower():
                raise
            logger.warning(
                "Anthropic rejected temperature=%s for model=%s; retrying without it",
                request.temperature, request.model,
            )
    return await client.messages.create(**kwargs)


class AnthropicProviderClient:
    @staticmethod
    def _build_messages(request: ExternalLLMRequest) -> list[dict]:
        messages = [msg for msg in request.history if msg["role"] in {"user", "assistant"}]
        if request.image_b64:
            messages.append({"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": request.image_mime or "image/jpeg",
                    "data": request.image_b64,
                }},
                {"type": "text", "text": request.query},
            ]})
        elif request.file_b64:
            # Same source block as the image above, different part type.
            messages.append({"role": "user", "content": [
                {"type": "document", "source": {
                    "type": "base64",
                    "media_type": request.file_mime or "application/pdf",
                    "data": request.file_b64,
                }},
                {"type": "text", "text": request.query},
            ]})
        else:
            messages.append({"role": "user", "content": request.query})

        return messages

    async def generate_response(self, request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse:
        ensure_query(request)

        _clear_client_cache_if_factory_changed()
        client = _get_client(api_key)
        messages = self._build_messages(request)

        logger.debug("Sending hard query to Anthropic model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        with _mapped_errors(api_key):
            response = await _create_with_temperature_retry(
                client, request,
                model=request.model,
                system=request.system_prompt,
                messages=messages,
                max_tokens=request.max_tokens,
            )

        latency_ms = elapsed_ms(start)
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
            finish_reason=normalize_finish_reason(response.stop_reason),
        )

    async def stream_response(
        self, request: ExternalLLMRequest, api_key: str
    ) -> AsyncGenerator[ExternalStreamChunk, None]:
        """Streaming twin of `generate_response`.

        Uses the raw `stream=True` event iterator rather than the SDK's
        `messages.stream()` helper: the helper's context manager and its
        `get_final_message()` accumulate the whole message anyway, and the raw
        events already carry every field the terminal chunk needs.
        """
        ensure_query(request)

        _clear_client_cache_if_factory_changed()
        client = _get_client(api_key)
        messages = self._build_messages(request)

        logger.debug("Streaming hard query to Anthropic model=%s history_turns=%d", request.model, len(request.history))
        start = time.perf_counter()
        text = ""
        prompt_tokens = completion_tokens = 0
        stop_reason = None
        with _mapped_errors(api_key):
            stream = await _create_with_temperature_retry(
                client, request,
                model=request.model,
                system=request.system_prompt,
                messages=messages,
                max_tokens=request.max_tokens,
                stream=True,
            )
            # `async with`, not a bare `async for`: a client that disconnects
            # mid-answer closes this generator where it is suspended, and only
            # the SDK stream's own __aexit__ releases the upstream HTTPS
            # response back to the pool. Abandoning it leaks the connection for
            # as long as the aborted generation would have run.
            async with stream:
                async for event in stream:
                    kind = getattr(event, "type", "")
                    if kind == "message_start":
                        usage = getattr(event.message, "usage", None)
                        if usage:
                            prompt_tokens = usage.input_tokens or 0
                    elif kind == "content_block_delta":
                        piece = getattr(event.delta, "text", "") or ""
                        if piece:
                            text += piece
                            yield ExternalStreamChunk(text=piece)
                    elif kind == "message_delta":
                        stop_reason = getattr(event.delta, "stop_reason", None) or stop_reason
                        usage = getattr(event, "usage", None)
                        if usage:
                            completion_tokens = usage.output_tokens or completion_tokens

        yield ExternalStreamChunk(final=ExternalLLMResponse(
            text=text,
            model_used=request.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=elapsed_ms(start),
            finish_reason=normalize_finish_reason(stop_reason),
        ))
