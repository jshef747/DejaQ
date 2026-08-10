import time
import logging

from app.config import LOCAL_LLM_MODEL_NAME
from app.services.model_backends import (
    CompletionRequest,
    ModelBackend,
    complete_with_default_fallback,
)

logger = logging.getLogger("dejaq.services.llm_router")


class LLMRouterService:
    def __init__(self, backend: ModelBackend, model_name: str):
        self.backend = backend
        self.model_name = model_name

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
        if system_prompt is None:
            system_prompt = "You are a helpful assistant. Answer the user's query concisely and accurately."
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})
        start = time.time()
        request = CompletionRequest(
            model_name=self.model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        # A workspace override may name a model since uninstalled from Ollama -
        # write-time validation can't catch this day-2 drift, so fall back to
        # the shipped default rather than surfacing a raw 500.
        response = await complete_with_default_fallback(
            self.backend, request, LOCAL_LLM_MODEL_NAME, "local answering"
        )
        latency_ms = (time.time() - start) * 1000
        logger.debug("Local LLM response generated in %.2f ms", latency_ms)
        return response.text, latency_ms, response.done_reason

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
