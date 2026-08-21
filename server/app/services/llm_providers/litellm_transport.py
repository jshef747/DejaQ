import logging
import time
from collections.abc import AsyncGenerator, Iterator
from contextlib import aclosing, contextmanager

import litellm
import openai

from app.schemas.chat import ExternalLLMRequest, ExternalLLMResponse, ExternalStreamChunk
from app.services.llm_providers._litellm_config import DEFAULT_CALL_KWARGS
from app.services.llm_providers.common import (
    elapsed_ms,
    ensure_query,
    estimate_tokens,
    normalize_finish_reason,
    redact_api_key,
)
from app.utils.exceptions import (
    ExternalAttachmentTooLargeError,
    ExternalAttachmentUnsupportedError,
    ExternalLLMAuthError,
    ExternalLLMError,
    ExternalLLMTimeoutError,
)

logger = logging.getLogger("dejaq.services.llm_providers.litellm_transport")

# DejaQ's provider keys are not all LiteLLM's. `google`, `together` and
# `fireworks` are not real LiteLLM provider names (verified against
# litellm.provider_list); LiteLLM's names are `gemini`, `together_ai` and
# `fireworks_ai`. The other seven DejaQ providers match. Migration stage A2
# deletes this map by moving DejaQ onto LiteLLM's own provider namespace.
_LITELLM_PROVIDER_KEYS = {
    "google": "gemini",
    "together": "together_ai",
    "fireworks": "fireworks_ai",
}

# Exit seam (plan section 4, row 7): the three non-default hosts the deleted
# `provider_registry.ProviderSpec.base_url` used to carry, so a hand-written
# client restored later already knows every host instead of re-deriving them
# from vendor docs under pressure. Dead as data - LiteLLM resolves each
# provider's host internally from the `provider/model` string, nothing here
# reads these.
#   xai:      https://api.x.ai/v1
#   deepseek: https://api.deepseek.com
#   groq:     https://api.groq.com/openai/v1

# litellm.request_timeout defaults to 6000.0 seconds (100 minutes); every
# call must pass its own timeout rather than inherit that.
_REQUEST_TIMEOUT_SECONDS = 60.0


def _litellm_key(provider: str) -> str:
    return _LITELLM_PROVIDER_KEYS.get(provider, provider)


def _confirmed_incapable(model: str, capability_field: str) -> bool:
    """True only when LiteLLM's own catalog affirmatively lacks `capability_field`
    for `model` (e.g. "supports_vision", "supports_pdf_input").

    False both when the model has the capability AND when LiteLLM has no
    catalog entry for it at all (`get_model_info` raises for an id it
    doesn't recognise, which is a data gap, not proof of incapability) - a
    model this returns False for is left to reach the provider exactly as
    before this check existed, so an unmapped-but-real vision/document model
    is never blocked.
    """
    try:
        info = litellm.get_model_info(model)
    except Exception:
        return False
    return not info.get(capability_field)


def _confirmed_context_budget(model: str) -> int | None:
    """The model's own max input-token budget, per LiteLLM's catalog, or
    None when the catalog has no entry for it.

    None is deliberately "unknown, don't block" (the same conservative bias
    `_confirmed_incapable` uses) rather than falling back to a hardcoded
    guess - an uncatalogued model reaches the provider exactly as it did
    before this check existed.
    """
    try:
        info = litellm.get_model_info(model)
    except Exception:
        return None
    return info.get("max_input_tokens") or info.get("max_tokens")


def _build_messages(request: ExternalLLMRequest) -> list[dict]:
    messages = [{"role": "system", "content": request.system_prompt}]
    messages.extend(request.history)
    if request.image_b64:
        if _confirmed_incapable(request.model, "supports_vision"):
            raise ExternalAttachmentUnsupportedError(request.model, "image")
        user_content = [
            {"type": "text", "text": request.query},
            {"type": "image_url", "image_url": {
                "url": f"data:{request.image_mime or 'image/jpeg'};base64,{request.image_b64}"
            }},
        ]
    elif request.file_b64:
        if _confirmed_incapable(request.model, "supports_pdf_input"):
            raise ExternalAttachmentUnsupportedError(request.model, "document")
        user_content = [
            {"type": "text", "text": request.query},
            {"type": "file", "file": {
                "filename": request.file_name or "document.pdf",
                "file_data": f"data:{request.file_mime or 'application/pdf'};base64,{request.file_b64}",
            }},
        ]
    else:
        # No native attachment part on this branch - a plain query, or a
        # text/Markdown/code attachment already inlined into request.query
        # by _query_with_inlined_file. Nothing bounds that text against the
        # model's own context window before it reaches the wire, unlike the
        # local path's local_attachment_max_tokens - so check it here, the
        # one place both generate_response and stream_response route
        # through, rather than in every caller.
        budget = _confirmed_context_budget(request.model)
        if budget is not None:
            history_chars = sum(
                len(m.get("content", "")) for m in request.history if isinstance(m.get("content"), str)
            )
            estimated_tokens = estimate_tokens(request.system_prompt) + estimate_tokens(request.query)
            estimated_tokens += history_chars // 3
            if estimated_tokens + request.max_tokens > budget:
                raise ExternalAttachmentTooLargeError(request.model, estimated_tokens, budget)
        user_content = request.query
    messages.append({"role": "user", "content": user_content})
    return messages


async def _complete_with_temperature_retry(
    request: ExternalLLMRequest, messages: list[dict], model: str, api_key: str, **extra_kwargs: object,
):
    """Sends `temperature` only when the caller set one, and retries once
    without it if the vendor rejects it by name.

    `drop_params` is proactive only: it strips what LiteLLM's own parameter
    table already believes unsupported, and does nothing when a vendor
    rejects a parameter the table thought was fine - measured failing on
    gpt-5.6-terra and gpt-5.6-sol, both models DejaQ ships.
    """
    call_kwargs = dict(
        model=model, messages=messages, api_key=api_key,
        max_tokens=request.max_tokens, timeout=_REQUEST_TIMEOUT_SECONDS,
        drop_params=True, **DEFAULT_CALL_KWARGS, **extra_kwargs,
    )
    if request.temperature is not None:
        try:
            return await litellm.acompletion(temperature=request.temperature, **call_kwargs)
        except litellm.BadRequestError as exc:
            if "temperature" not in str(exc).lower():
                raise
            logger.warning(
                "LiteLLM rejected temperature=%s for model=%s; retrying without it",
                request.temperature, model,
            )
    return await litellm.acompletion(**call_kwargs)


@contextmanager
def _mapped_errors(api_key: str, provider: str) -> Iterator[None]:
    """Translate LiteLLM's exceptions into DejaQ's own.

    Ordered most-specific-first: `Timeout` subclasses `APIConnectionError`
    subclasses (openai.)`APIError`; `ContextWindowExceededError` and
    `UnsupportedParamsError` both subclass `BadRequestError`. The catch-all
    is `openai.APIError`, never `litellm.APIError` - no LiteLLM exception
    class subclasses the latter, they all subclass `openai.OpenAIError`.
    """
    try:
        yield
    except litellm.Timeout as exc:
        msg = redact_api_key(exc, api_key)
        logger.error("LiteLLM timeout (provider=%s): %s", provider, msg)
        raise ExternalLLMTimeoutError(f"Provider timeout: {msg}") from exc
    except litellm.APIConnectionError as exc:
        msg = redact_api_key(exc, api_key)
        logger.error("LiteLLM connection error (provider=%s): %s", provider, msg)
        raise ExternalLLMError(f"Provider error: {msg}", status_code=getattr(exc, "status_code", None)) from exc
    except litellm.AuthenticationError as exc:
        msg = redact_api_key(exc, api_key)
        logger.error("LiteLLM authentication failed (provider=%s): %s", provider, msg)
        raise ExternalLLMAuthError(
            f"Authentication failed: {msg}", status_code=getattr(exc, "status_code", None)
        ) from exc
    except litellm.RateLimitError as exc:
        msg = redact_api_key(exc, api_key)
        logger.error("LiteLLM rate limited (provider=%s): %s", provider, msg)
        raise ExternalLLMError(f"Provider error: {msg}", status_code=getattr(exc, "status_code", None)) from exc
    except (litellm.ContextWindowExceededError, litellm.UnsupportedParamsError, litellm.BadRequestError) as exc:
        msg = redact_api_key(exc, api_key)
        status_code = getattr(exc, "status_code", None)
        # The two Gemini lines. Gemini never 403s a bad parameter, so a 403
        # here is a rejected credential wearing a BadRequestError costume;
        # and "API_KEY_INVALID" is read out of the exception text ourselves
        # rather than trusting LiteLLM's own substring match on the English
        # sentence "API key not valid." Verified live against Google's own
        # endpoint by the migration spike. Live from stage L5 onward.
        if provider == "google" and (status_code == 403 or "API_KEY_INVALID" in str(exc)):
            logger.error("LiteLLM authentication failed (provider=%s): %s", provider, msg)
            raise ExternalLLMAuthError(f"Authentication failed: {msg}", status_code=401) from exc
        logger.error("LiteLLM bad request (provider=%s): %s", provider, msg)
        raise ExternalLLMError(f"Provider error: {msg}", status_code=status_code) from exc
    except openai.APIError as exc:
        msg = redact_api_key(exc, api_key)
        logger.error("LiteLLM provider error (provider=%s): %s", provider, msg)
        raise ExternalLLMError(f"Provider error: {msg}", status_code=getattr(exc, "status_code", None)) from exc


class LiteLLMTransportClient:
    """One `LLMProviderClient` implementation routing through LiteLLM.

    One instance per key in `llm_providers.LIVE_PROVIDERS`, built by
    `external_llm._PROVIDER_CLIENTS`. `provider` is DejaQ's own provider key,
    used only for error logging/mapping here - the wire model string comes
    straight from `request.model`, which is already LiteLLM-qualified (see
    `generate_response`).
    """

    def __init__(self, provider: str) -> None:
        self._provider = provider

    async def generate_response(self, request: ExternalLLMRequest, api_key: str) -> ExternalLLMResponse:
        ensure_query(request)
        messages = _build_messages(request)
        # request.model is already provider-qualified (stage A2's migration
        # qualified every stored row; stage A1a's write-time validation
        # rejects an unqualified name) - do not re-prefix it here.
        model = request.model

        logger.debug(
            "Sending hard query via LiteLLM provider=%s model=%s history_turns=%d",
            self._provider, request.model, len(request.history),
        )
        start = time.perf_counter()
        extra_kwargs = {"reasoning_format": "hidden"} if self._provider == "groq" else {}
        with _mapped_errors(api_key, self._provider):
            response = await _complete_with_temperature_retry(request, messages, model, api_key, **extra_kwargs)

        latency_ms = elapsed_ms(start)
        usage = response.usage
        choice = response.choices[0]
        content = choice.message.content or ""
        logger.debug(
            "LiteLLM request successful (provider=%s, model=%s, latency=%.2f ms, "
            "prompt_tokens=%d, completion_tokens=%d)",
            self._provider, request.model, latency_ms,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )
        return ExternalLLMResponse(
            text=content,
            # LiteLLM's own echoed `model` field is not the requested name
            # for a proxied or fake host - use DejaQ's own request field.
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

        Uses `contextlib.aclosing`, not `async with`: LiteLLM's
        `CustomStreamWrapper` has `aclose` but no `__aenter__`. Get this
        wrong and DejaQ leaks a connection per abandoned stream.
        """
        ensure_query(request)
        messages = _build_messages(request)
        # See generate_response - request.model is already provider-qualified.
        model = request.model

        logger.debug(
            "Streaming hard query via LiteLLM provider=%s model=%s history_turns=%d",
            self._provider, request.model, len(request.history),
        )
        start = time.perf_counter()
        text = ""
        prompt_tokens = completion_tokens = 0
        finish_reason = None
        extra_kwargs = {"reasoning_format": "hidden"} if self._provider == "groq" else {}
        with _mapped_errors(api_key, self._provider):
            stream = await _complete_with_temperature_retry(
                request, messages, model, api_key,
                stream=True, stream_options={"include_usage": True}, **extra_kwargs,
            )
        async with aclosing(stream):
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage:
                    prompt_tokens = usage.prompt_tokens or prompt_tokens
                    completion_tokens = usage.completion_tokens or completion_tokens
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
