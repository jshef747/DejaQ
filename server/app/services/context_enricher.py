import logging
import time
from typing import Optional

from app.services.model_loader import ModelManager

logger = logging.getLogger("dejaq.services.context_enricher")


class ContextEnricherService:
    """Rewrites context-dependent queries into standalone questions using conversation history."""

    def __init__(self):
        self.llm = ModelManager.load_qwen()

    def enrich(self, message: str, history: list[dict]) -> str:
        """Enrich a message with conversation context to make it standalone.

        If there's no history, returns the message as-is (skip inference).
        Uses last 3 turns (6 messages) of history for context.
        """
        if not history:
            logger.debug("No history — skipping enrichment for: %s", message[:80])
            return message

        # Take last 3 turns (up to 6 messages)
        recent_history = history[-6:]

        # Build context string from history
        context_lines = []
        for msg in recent_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            context_lines.append(f"{role}: {msg['content']}")
        context_block = "\n".join(context_lines)

        start = time.time()

        output = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "You are a query rewriter. Given a conversation history and a follow-up message, rewrite the follow-up into a standalone question that includes all necessary context. Output ONLY the rewritten question. If the message is already standalone, return it unchanged."},
                # Example 1: pronoun resolution
                {"role": "user", "content": "HISTORY:\nUser: What is Python?\nAssistant: Python is a high-level programming language.\n\nFOLLOW-UP: Tell me more about its features"},
                {"role": "assistant", "content": "What are the main features of the Python programming language?"},
                # Example 2: topic continuation
                {"role": "user", "content": "HISTORY:\nUser: How does photosynthesis work?\nAssistant: Photosynthesis converts light energy into chemical energy in plants.\n\nFOLLOW-UP: What about the dark reactions?"},
                {"role": "assistant", "content": "What are the dark reactions in photosynthesis?"},
                # Example 3: resolve reference from assistant's answer
                {"role": "user", "content": "HISTORY:\nUser: What is the capital of Italy?\nAssistant: The capital of Italy is Rome.\n\nFOLLOW-UP: I am traveling there recommend me restaurants"},
                {"role": "assistant", "content": "What restaurants should I visit in Rome?"},
                # Example 4: already standalone
                {"role": "user", "content": "HISTORY:\nUser: What is gravity?\nAssistant: Gravity is a fundamental force of attraction.\n\nFOLLOW-UP: What is the capital of France?"},
                {"role": "assistant", "content": "What is the capital of France?"},
                # Actual query
                {"role": "user", "content": f"HISTORY:\n{context_block}\n\nFOLLOW-UP: {message}"},
            ],
            max_tokens=64,
            temperature=0.0
        )

        enriched = output["choices"][0]["message"]["content"].strip()
        latency = (time.time() - start) * 1000
        logger.info(
            "Enrichment completed in %.2f ms. Original: '%s' -> Enriched: '%s'",
            latency, message[:60], enriched[:60],
        )
        return enriched
