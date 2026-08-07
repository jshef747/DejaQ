from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, TypedDict

import httpx

logger = logging.getLogger("dejaq.services.model_backends")


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


class ModelBackend(Protocol):
    async def complete(self, request: CompletionRequest) -> str:
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
        try:
            return MODEL_RUNTIME_SPECS[logical_model_name].ollama_model
        except KeyError as exc:
            raise ValueError(f"Unknown logical model name: {logical_model_name}") from exc

    async def complete(self, request: CompletionRequest) -> str:
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

        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Ollama response missing assistant message content")
        return content.strip()
