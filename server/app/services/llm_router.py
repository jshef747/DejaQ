import time
import logging
from collections.abc import AsyncGenerator

from app.config import LOCAL_LLM_MODEL_NAME
from app.services.model_backends import (
    CompletionChunk,
    CompletionRequest,
    ModelBackend,
    complete_with_default_fallback,
    stream_with_default_fallback,
)

logger = logging.getLogger("dejaq.services.llm_router")

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Answer the user's query concisely and accurately."


class LLMRouterService:
    def __init__(self, backend: ModelBackend, model_name: str, default_system_prompt: str | None = None):
        self.backend = backend
        self.model_name = model_name
        # The per-workspace default for this role - only used when a caller
        # supplies no system_prompt of its own (see generate_local_response
        # below). A client-sent prompt always wins over this.
        self.default_system_prompt = (
            default_system_prompt if default_system_prompt is not None else DEFAULT_SYSTEM_PROMPT
        )

    def is_hard(self, complexity: str) -> bool:
        return complexity == "hard"

    async def generate_local_response(
        self,
        query: str,
        history: list[dict] | None = None,
        max_tokens: int = 1024,
        system_prompt: str | None = None,
    ) -> tuple[str, float, str | None]:
        """Generate a response using the local model. Returns (text, latency_ms, done_reason)."""
        request = self._completion_request(query, history, max_tokens, system_prompt)
        start = time.time()
        # A workspace override may name a model since uninstalled from Ollama -
        # write-time validation can't catch this day-2 drift, so fall back to
        # the shipped default rather than surfacing a raw 500.
        response = await complete_with_default_fallback(
            self.backend, request, LOCAL_LLM_MODEL_NAME, "local answering"
        )
        latency_ms = (time.time() - start) * 1000
        logger.debug("Local LLM response generated in %.2f ms", latency_ms)
        return response.text, latency_ms, response.done_reason

    def _completion_request(
        self,
        query: str,
        history: list[dict] | None,
        max_tokens: int,
        system_prompt: str | None,
    ) -> CompletionRequest:
        if system_prompt is None:
            system_prompt = self.default_system_prompt
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})
        return CompletionRequest(
            model_name=self.model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )

    async def stream_local_response(
        self,
        query: str,
        history: list[dict] | None = None,
        max_tokens: int = 1024,
        system_prompt: str | None = None,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Streaming twin of `generate_local_response`.

        Yields the answer as the model produces it; the final chunk carries
        `done_reason`, which the caller reads for truncation exactly as it
        reads `CompletionResult.done_reason` on the non-streaming call.
        """
        request = self._completion_request(query, history, max_tokens, system_prompt)
        start = time.time()
        async for chunk in stream_with_default_fallback(
            self.backend, request, LOCAL_LLM_MODEL_NAME, "local answering"
        ):
            yield chunk
        logger.debug("Local LLM stream finished in %.2f ms", (time.time() - start) * 1000)

    # Kept for backwards compatibility — used by tests and callers that don't need metadata.
    async def generate_response(self, query: str, complexity: str, history: list[dict] | None = None) -> str:
        logger.debug("Routing query complexity=%s", complexity)
        if not self.is_hard(complexity):
            text, _, _ = await self.generate_local_response(query, history=history)
            return text
        # Hard queries must be handled asynchronously by the caller via ExternalLLMService.
        # This path should not be reached in normal operation after the external routing integration.
        logger.warning("generate_response called for hard query — falling back to local model. Use ExternalLLMService instead.")
        text, _, _ = await self.generate_local_response(query, history=history)
        return text
