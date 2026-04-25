import logging
import time

from app.services.model_backends import CompletionRequest, ModelBackend

logger = logging.getLogger("dejaq.services.context_adjuster")


class ContextAdjusterService:

    def __init__(
        self,
        adjust_backend: ModelBackend,
        adjust_model_name: str,
        generalize_backend: ModelBackend,
        generalize_model_name: str,
    ):
        self.adjust_backend = adjust_backend
        self.adjust_model_name = adjust_model_name
        self.generalize_backend = generalize_backend
        self.generalize_model_name = generalize_model_name

    async def generalize(self, answer: str) -> str:
        logger.debug(f"Generalizing response: {answer[:80]}...")

        start = time.time()

        generalized = await self.generalize_backend.complete(
            CompletionRequest(
                model_name=self.generalize_model_name,
                messages=[
                {"role": "system", "content": "Rewrite the ANSWER into a neutral, factual tone. Remove slang, humor, and personality. Keep all facts. Output only the rewritten answer."},
                # Example 1: casual → neutral
                {"role": "user", "content": "ANSWER: Yo, so basically gravity is like the Earth just pulling stuff down, ya know? Like when you toss a ball up it comes right back!"},
                {"role": "assistant", "content": "Gravity is a fundamental force that causes objects with mass to attract one another. When an object is thrown upward near Earth's surface, gravitational pull causes it to return to the ground."},
                # Example 2: child-friendly → neutral
                {"role": "user", "content": "ANSWER: Paris is the big fancy city where the Eiffel Tower lives! It's the capital of France and people eat yummy croissants there!"},
                {"role": "assistant", "content": "Paris is the capital city of France. It is known for landmarks such as the Eiffel Tower."},
                # Example 3: already neutral (should pass through)
                {"role": "user", "content": "ANSWER: Photosynthesis is the process by which plants convert light energy into chemical energy, producing glucose and oxygen from carbon dioxide and water."},
                {"role": "assistant", "content": "Photosynthesis is the process by which plants convert light energy into chemical energy, producing glucose and oxygen from carbon dioxide and water."},
                # Actual answer
                {"role": "user", "content": f"ANSWER: {answer}"},
                ],
                max_tokens=1024,
                temperature=0.3,
            )
        )

        latency = (time.time() - start) * 1000
        logger.debug("Generalization completed in %.2f ms", latency)
        return generalized

    async def adjust(self, original_query: str, general_answer: str) -> str:
        logger.debug(f"Adjusting response for original query: {original_query}")

        start = time.time()

        adjusted = await self.adjust_backend.complete(
            CompletionRequest(
                model_name=self.adjust_model_name,
                messages=[
                {"role": "system", "content": "Rewrite the ANSWER to match the tone of the QUESTION. Keep all facts. Output only the rewritten answer."},
                # Example 1: casual/child tone
                {"role": "user", "content": "QUESTION: explain gravity like I'm 5\nANSWER: Gravity is a fundamental force of attraction between objects with mass."},
                {"role": "assistant", "content": "Imagine you have a ball. When you throw it up, it comes back down! That's because the Earth is really big and pulls everything toward it. That pulling is called gravity!"},
                # Example 2: casual/brief tone
                {"role": "user", "content": "QUESTION: yo whats the capital of france\nANSWER: The capital of France is Paris."},
                {"role": "assistant", "content": "It's Paris!"},
                # Example 3: formal/detailed tone
                {"role": "user", "content": "QUESTION: provide a detailed analysis of photosynthesis\nANSWER: Photosynthesis is how plants make food from sunlight."},
                {"role": "assistant", "content": "Photosynthesis is the biochemical process by which plants, algae, and certain bacteria convert light energy into chemical energy. During this process, carbon dioxide and water are transformed into glucose and oxygen through light-dependent and light-independent reactions within the chloroplasts."},
                # Actual query
                {"role": "user", "content": f"QUESTION: {original_query}\nANSWER: {general_answer}"},
                ],
                max_tokens=1024,
                temperature=0.3,
            )
        )

        latency = (time.time() - start) * 1000
        logger.debug("Context adjustment completed in %.2f ms", latency)
        return adjusted
