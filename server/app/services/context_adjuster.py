import logging
import time

from app.services.model_loader import ModelManager

logger = logging.getLogger("dejaq.services.context_adjuster")


class ContextAdjusterService:

    def __init__(self):
        self.llm = ModelManager.load_qwen_1_5b()
        self.generalize_llm = ModelManager.load_phi()

    def generalize(self, answer: str) -> str:
        logger.debug(f"Generalizing response: {answer[:80]}...")

        start = time.time()

        output = self.generalize_llm.create_chat_completion(
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
            max_tokens=256,
            temperature=0.3
        )

        generalized = output["choices"][0]["message"]["content"].strip()
        latency = (time.time() - start) * 1000
        logger.info(f"Generalization completed in {latency:.2f} ms")
        return generalized

    def adjust(self, original_query: str, general_answer: str) -> str:
        logger.debug(f"Adjusting response for original query: {original_query}")

        start = time.time()

        output = self.llm.create_chat_completion(
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
            max_tokens=256,
            temperature=0.3
        )

        adjusted = output["choices"][0]["message"]["content"].strip()
        latency = (time.time() - start) * 1000
        logger.info(f"Context adjustment completed in {latency:.2f} ms for query: {original_query}")
        return adjusted
