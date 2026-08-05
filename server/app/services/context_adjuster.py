import logging
import re
import time

from app.config import ADJUSTER_MIN_TOPIC_OVERLAP
from app.services.model_backends import CompletionRequest, ModelBackend

logger = logging.getLogger("dejaq.services.context_adjuster")

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common function words, excluded so overlap is measured on content words only.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "so", "of", "in", "on", "at",
    "to", "for", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "it", "its", "this", "that", "these", "those", "i", "you",
    "he", "she", "we", "they", "my", "your", "his", "her", "our", "their",
    "do", "does", "did", "can", "could", "will", "would", "should", "may",
    "might", "must", "not", "no", "yes", "than", "then", "there", "here",
    "when", "where", "how", "what", "who", "why", "which", "into", "onto",
    "about", "also", "more", "most", "other", "some", "any", "each", "all",
    "have", "has", "had", "such", "up", "out", "over", "under", "again",
    "further", "once",
})


def _content_words(text: str) -> frozenset[str]:
    return frozenset(
        w for w in _TOKEN_RE.findall(text.lower())
        if len(w) >= 3 and w not in _STOPWORDS
    )


def is_topically_consistent(adjusted: str, cached_answer: str) -> bool:
    """Cheap lexical safety net for the tone-adjustment step.

    Guards against the small adjuster model pattern-matching on the SHAPE of a
    request ("give me something more detailed") and regurgitating unrelated
    content instead of rewriting the real cached answer. A genuine tone
    rewrite can legitimately drop most of the cached wording (an ELI5 rewrite
    of "a fundamental force of attraction between objects with mass" keeps
    only the word "gravity"), so this checks for ANY meaningful surviving
    overlap rather than a high similarity bar: a real rewrite keeps at least a
    sliver of the original vocabulary, a fabricated off-topic answer keeps
    essentially none. Pure stdlib, no model call: this must stay cheap since
    it runs on the cache-hit path.
    """
    cached_words = _content_words(cached_answer)
    if not cached_words:
        return True  # nothing meaningful to compare against; don't block on it
    adjusted_words = _content_words(adjusted)
    overlap = len(cached_words & adjusted_words)
    return (overlap / len(cached_words)) >= ADJUSTER_MIN_TOPIC_OVERLAP


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
                # A third example demonstrating the formal/detailed direction used
                # to live here, e.g. "provide a detailed analysis of photosynthesis".
                # Removed: on a 148-query eval, 9/88 cache hits (10.2%) came back as
                # a paraphrase of THAT example's assistant turn, a well-written but
                # completely unrelated answer, whenever a real QUESTION merely
                # resembled its shape ("give me something more detailed"). The small
                # model was pattern-matching the request shape and regurgitating the
                # example's own content instead of conditioning on the real ANSWER.
                # The system prompt above already states the instruction; two
                # examples are enough to demonstrate style transfer without handing
                # the model a topic it can fall back on.
                # Actual query
                {"role": "user", "content": f"QUESTION: {original_query}\nANSWER: {general_answer}"},
                ],
                max_tokens=1024,
                # Deterministic: this is a faithful rewrite, not creative
                # generation, so temperature buys nothing here and only made the
                # regurgitation failure above intermittent and hard to reproduce.
                temperature=0,
            )
        )

        latency = (time.time() - start) * 1000
        logger.debug("Context adjustment completed in %.2f ms", latency)

        if not is_topically_consistent(adjusted, general_answer):
            logger.warning(
                "Context adjuster output failed topic-consistency check; "
                "serving cached answer verbatim instead of the drifted rewrite"
            )
            return general_answer

        return adjusted
