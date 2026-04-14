import time
import logging
from app.services.model_loader import ModelManager

logger = logging.getLogger("dejaq.services.llm_router")

_LOCAL_MODEL_NAME = "gemma-4-e4b"


class LLMRouterService:
    def __init__(self):
        self.local_llm = ModelManager.load_gemma()

    def is_hard(self, complexity: str) -> bool:
        return complexity == "hard"

    def generate_local_response(
        self,
        query: str,
        history: list[dict] | None = None,
        max_tokens: int = 1024,
        system_prompt: str | None = None,
    ) -> tuple[str, float]:
        """Generate a response using the local model. Returns (text, latency_ms)."""
        if system_prompt is None:
            system_prompt = "You are a helpful assistant. Answer the user's query concisely and accurately."
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})
        start = time.time()
        output = self.local_llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        response = output["choices"][0]["message"]["content"].strip()
        latency_ms = (time.time() - start) * 1000
        logger.debug("Local LLM response generated in %.2f ms for query: %s", latency_ms, query)
        return response, latency_ms

    # Kept for backwards compatibility — used by tests and callers that don't need metadata.
    def generate_response(self, query: str, complexity: str, history: list[dict] | None = None) -> str:
        logger.info("Routing query (complexity=%s): %.80s", complexity, query)
        if not self.is_hard(complexity):
            text, _ = self.generate_local_response(query, history=history)
            return text
        # Hard queries must be handled asynchronously by the caller via ExternalLLMService.
        # This path should not be reached in normal operation after the external routing integration.
        logger.warning("generate_response called for hard query — falling back to local model. Use ExternalLLMService instead.")
        text, _ = self.generate_local_response(query, history=history)
        return text