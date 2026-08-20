from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from typing import Protocol, TypedDict

import httpx

logger = logging.getLogger("dejaq.services.model_backends")


class ModelNotFoundError(Exception):
    """Raised when Ollama reports a model tag as not installed.

    Distinct from the logical-name KeyError case: a workspace pipeline
    override names a raw Ollama tag (captain's decision - any installed tag
    is selectable, not just ones in MODEL_RUNTIME_SPECS), validated against
    the live catalog at write time. This is the day-2-drift case that write-
    time validation cannot catch - the tag was uninstalled after it was
    saved. Every overridable role (generalizer, adjuster, local-answering,
    enricher, normalizer, validator) catches this - via
    complete_with_default_fallback() below - and falls back to the shipped
    default rather than surfacing a raw 500 three steps into the pipeline.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"Ollama model not found: {model_name}")


class LocalVisionUnsupportedError(Exception):
    """Raised when Ollama rejects an image-bearing call because the model
    itself cannot accept images - the model exists (unlike ModelNotFoundError),
    it just isn't vision-capable.

    This is the safety net for the capability cache's staleness window
    (ollama_catalog.supports_vision, TTL-cached): a caller should check
    capability before sending an image, but between a cache refresh and an
    admin swapping the workspace's local model in Ollama, the cached answer
    can be wrong. Matched defensively by status code (400 or 500) on a call
    that carried images, not by Ollama's exact error text, which is
    version-dependent (confirmed 400 + "Multimodal data provided, but model
    does not support multimodal requests." on server 0.32.5; older builds are
    reported to return 500 with different wording).
    """

    def __init__(self, model_name: str, detail: str) -> None:
        self.model_name = model_name
        self.detail = detail
        super().__init__(f"Ollama model {model_name} rejected an image-bearing request: {detail}")


def _ollama_error_detail(body: bytes) -> str:
    """Best-effort human-readable text from an Ollama error response body."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body.decode("utf-8", errors="replace")
    if isinstance(data, dict):
        return str(data.get("error", data))
    return str(data)


class PromptMessage(TypedDict):
    role: str
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    model_name: str
    messages: list[PromptMessage]
    max_tokens: int
    temperature: float
    stop: list[str] | None = None
    # Context window for this call only. Left None, Ollama uses its own runtime
    # default, which is what every role wants: a window is memory (the KV cache
    # is allocated at that size per loaded model) and only a caller whose prompt
    # plus generation can approach it has anything to gain. Set it there, not
    # here — see generalize()/adjust() in services/context_adjuster.py.
    num_ctx: int | None = None
    # Base64-encoded images, attached to the final message per Ollama's wire
    # format (`images` on a chat message, not a top-level request field). Unused
    # by every caller today - no code path passes this yet.
    images: list[str] | None = None


@dataclass(frozen=True)
class ModelRuntimeSpec:
    ollama_model: str


MODEL_RUNTIME_SPECS: dict[str, ModelRuntimeSpec] = {
    "qwen_0_5b": ModelRuntimeSpec(ollama_model="qwen2.5:0.5b"),
    "qwen_1_5b": ModelRuntimeSpec(ollama_model="qwen2.5:1.5b"),
    "gemma_e2b": ModelRuntimeSpec(ollama_model="gemma4:e2b"),
    "gemma_local": ModelRuntimeSpec(ollama_model="gemma4:e4b"),
    "phi_generalizer": ModelRuntimeSpec(ollama_model="phi3.5:latest"),
}


@dataclass(frozen=True)
class CompletionResult:
    text: str
    # Ollama's own done_reason ("stop", "length", ...), passed through
    # unchanged rather than normalized here — every caller that cares about
    # truncation specifically checks for "length"; a caller that doesn't care
    # can ignore the field entirely. Normalizing "was this truncated" belongs
    # at each call site, since only the caller knows whether truncation is
    # actionable for that role (see generalize()/adjust() in
    # services/context_adjuster.py, the two roles that act on it).
    done_reason: str | None = None


@dataclass(frozen=True)
class CompletionChunk:
    """One incremental piece of a streamed completion.

    `text` carries the new characters; the final chunk carries `done_reason`
    with an empty `text`, so a caller that only wants the text can concatenate
    every `text` blindly and a caller that cares about truncation reads the
    last chunk's `done_reason` — the same field `CompletionResult` exposes.
    """

    text: str = ""
    done_reason: str | None = None


class ModelBackend(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResult:
        ...

    def stream(self, request: CompletionRequest) -> AsyncGenerator[CompletionChunk, None]:
        ...


async def complete_with_default_fallback(
    backend: ModelBackend,
    request: CompletionRequest,
    default_model_name: str,
    role: str,
) -> CompletionResult:
    """Run `request`, retrying on the shipped default if the model is gone.

    The single place the day-2-drift rule lives, so wiring a new role to a
    per-workspace override cannot silently ship without it (§
    ModelNotFoundError above). Re-raises when the shipped default is itself
    the missing model - that is a broken Ollama install, not drift, and
    retrying it would only repeat the same 404.
    """
    try:
        return await backend.complete(request)
    except ModelNotFoundError as exc:
        if request.model_name == default_model_name:
            raise
        logger.warning(
            "%s model=%s not installed in Ollama; falling back to shipped default=%s",
            role, exc.model_name, default_model_name,
        )
        return await backend.complete(replace(request, model_name=default_model_name))


async def stream_with_default_fallback(
    backend: ModelBackend,
    request: CompletionRequest,
    default_model_name: str,
    role: str,
) -> AsyncGenerator[CompletionChunk, None]:
    """Streaming twin of `complete_with_default_fallback`.

    Safe to retry mid-call: Ollama answers 404 for a missing tag when the
    response is opened, before any chunk has been yielded, so the fallback
    cannot replay text a caller already saw.
    """
    try:
        stream = backend.stream(request)
        first = await anext(stream, None)
    except ModelNotFoundError as exc:
        if request.model_name == default_model_name:
            raise
        logger.warning(
            "%s model=%s not installed in Ollama; falling back to shipped default=%s",
            role, exc.model_name, default_model_name,
        )
        async for chunk in backend.stream(replace(request, model_name=default_model_name)):
            yield chunk
        return
    if first is not None:
        yield first
        async for chunk in stream:
            yield chunk


class OllamaBackend:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _resolve_model(self, logical_model_name: str) -> str:
        spec = MODEL_RUNTIME_SPECS.get(logical_model_name)
        if spec is not None:
            return spec.ollama_model
        # Not a registered logical name: a per-workspace pipeline override
        # (dashboard picker) names a real Ollama tag directly, validated at
        # write time against a live `/api/tags` call rather than this static
        # dict - see services/llm_config_service.py. Pass it through as-is;
        # if it is no longer installed, Ollama's own /api/chat call below
        # raises ModelNotFoundError for the caller to catch.
        return logical_model_name

    def _payload(self, request: CompletionRequest, ollama_model: str, stream: bool) -> dict:
        messages = request.messages
        if request.images:
            # Ollama attaches images per-message, not at the request top level.
            # Copy rather than mutate the caller's last message dict in place.
            messages = list(messages)
            messages[-1] = {**messages[-1], "images": request.images}
        payload = {
            "model": ollama_model,
            "messages": messages,
            "stream": stream,
            # Gemma 4 is a thinking model: left alone it emits a `thinking` block
            # BEFORE `content`, and both are drawn from the same num_predict
            # budget. Measured on gemma4:e4b with num_predict=1024, a complexity
            # -theory question spent the entire budget on 3,301 characters of
            # thinking and returned content="" — a 20-second request that
            # produced a blank answer, which then got queued for caching. The
            # same prompt with think disabled returns 3,370 characters of answer.
            # Every role here wants the answer, never the scratchpad, so this is
            # off for all of them. Harmless on non-thinking models.
            "think": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if request.stop:
            payload["options"]["stop"] = request.stop
        if request.num_ctx is not None:
            payload["options"]["num_ctx"] = request.num_ctx
        return payload

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        ollama_model = self._resolve_model(request.model_name)
        logger.debug(
            "Model completion backend=ollama model=%s ollama_model=%s url=%s",
            request.model_name,
            ollama_model,
            self._base_url,
        )
        payload = self._payload(request, ollama_model, stream=False)

        if self._client is not None:
            response = await self._client.post("/api/chat", json=payload)
        else:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post("/api/chat", json=payload)

        if response.status_code == 404:
            # Ollama's shape for "model not installed" ({"error": "model
            # 'x' not found"}), confirmed against a live instance - the
            # day-2-drift case a workspace override cannot be pre-validated
            # against (§ ModelNotFoundError above).
            raise ModelNotFoundError(ollama_model)
        if request.images and response.status_code in (400, 500):
            # § LocalVisionUnsupportedError - only for an image-bearing call,
            # so an unrelated 400/500 on a text-only request is never
            # misattributed to a capability mismatch.
            raise LocalVisionUnsupportedError(ollama_model, _ollama_error_detail(response.content))
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Ollama response missing assistant message content")
        return CompletionResult(text=content.strip(), done_reason=data.get("done_reason"))

    async def stream(self, request: CompletionRequest) -> AsyncGenerator[CompletionChunk, None]:
        """Yield the answer as Ollama produces it.

        Same call as `complete`, with `stream: true`: Ollama answers with one
        JSON object per line, each carrying the newly generated characters,
        and a final object carrying `done_reason`. The 404 for a missing tag
        arrives on the response head, before any line — see
        `stream_with_default_fallback`.
        """
        ollama_model = self._resolve_model(request.model_name)
        logger.debug(
            "Model stream backend=ollama model=%s ollama_model=%s url=%s",
            request.model_name,
            ollama_model,
            self._base_url,
        )
        payload = self._payload(request, ollama_model, stream=True)

        has_images = bool(request.images)
        if self._client is not None:
            async for chunk in self._stream_lines(self._client, payload, ollama_model, has_images):
                yield chunk
            return
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
        ) as client:
            async for chunk in self._stream_lines(client, payload, ollama_model, has_images):
                yield chunk

    @staticmethod
    async def _stream_lines(
        client: httpx.AsyncClient, payload: dict, ollama_model: str, has_images: bool = False
    ) -> AsyncGenerator[CompletionChunk, None]:
        async with client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code == 404:
                raise ModelNotFoundError(ollama_model)
            if has_images and response.status_code in (400, 500):
                # § LocalVisionUnsupportedError - streaming twin of the check in
                # complete(); the body isn't loaded yet on a streamed response.
                body = await response.aread()
                raise LocalVisionUnsupportedError(ollama_model, _ollama_error_detail(body))
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Ollama stream produced a non-JSON line; ignoring it")
                    continue
                if data.get("error"):
                    raise ValueError(f"Ollama stream error: {data['error']}")
                text = data.get("message", {}).get("content") or ""
                if text:
                    yield CompletionChunk(text=text)
                if data.get("done"):
                    yield CompletionChunk(done_reason=data.get("done_reason"))
