from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol, TypedDict

import httpx

from app.services.model_loader import ModelManager

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


@dataclass(frozen=True)
class ModelRuntimeSpec:
    loader_name: str
    ollama_model: str


MODEL_RUNTIME_SPECS: dict[str, ModelRuntimeSpec] = {
    "qwen_0_5b": ModelRuntimeSpec(
        loader_name="load_qwen",
        ollama_model="qwen2.5:0.5b",
    ),
    "qwen_1_5b": ModelRuntimeSpec(
        loader_name="load_qwen_1_5b",
        ollama_model="qwen2.5:1.5b",
    ),
    "gemma_e2b": ModelRuntimeSpec(
        loader_name="load_gemma_e2b",
        ollama_model="gemma4:e2b",
    ),
    "gemma_local": ModelRuntimeSpec(
        loader_name="load_gemma",
        ollama_model="gemma4:e4b",
    ),
    "phi_generalizer": ModelRuntimeSpec(
        loader_name="load_phi",
        ollama_model="phi3.5:latest",
    ),
}


class ModelBackend(Protocol):
    async def complete(self, request: CompletionRequest) -> str:
        ...


class InProcessBackend:
    def _get_model(self, logical_model_name: str):
        try:
            runtime_spec = MODEL_RUNTIME_SPECS[logical_model_name]
        except KeyError as exc:
            raise ValueError(f"Unknown logical model name: {logical_model_name}") from exc

        loader = getattr(ModelManager, runtime_spec.loader_name, None)
        if loader is None:
            raise ValueError(
                f"Model loader '{runtime_spec.loader_name}' missing for logical model '{logical_model_name}'"
            )
        return loader()

    async def complete(self, request: CompletionRequest) -> str:
        logger.debug("Model completion backend=in_process model=%s", request.model_name)
        model = self._get_model(request.model_name)

        def _run_completion() -> str:
            output = model.create_chat_completion(
                messages=request.messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
            return output["choices"][0]["message"]["content"].strip()

        return await asyncio.to_thread(_run_completion)


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
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

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
