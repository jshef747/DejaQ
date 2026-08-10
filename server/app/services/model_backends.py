from __future__ import annotations

import logging
from dataclasses import dataclass
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
    saved. Callers for the three overridable roles (generalizer, adjuster,
    local-answering) catch this and fall back to the shipped default rather
    than surfacing a raw 500 three steps into the pipeline.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"Ollama model not found: {model_name}")


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


class ModelBackend(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResult:
        ...


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

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        ollama_model = self._resolve_model(request.model_name)
        logger.debug(
            "Model completion backend=ollama model=%s ollama_model=%s url=%s",
            request.model_name,
            ollama_model,
            self._base_url,
        )
        payload = {
            "model": ollama_model,
            "messages": request.messages,
            "stream": False,
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
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Ollama response missing assistant message content")
        return CompletionResult(text=content.strip(), done_reason=data.get("done_reason"))
