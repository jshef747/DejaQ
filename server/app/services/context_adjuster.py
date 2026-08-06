import logging
import re
import time
from collections import Counter

from app.config import (
    ADJUSTER_MIN_TOPIC_OVERLAP,
    GENERALIZE_LENGTH_ABS_FLOOR,
    GENERALIZE_LENGTH_RATIO_MAX,
    GENERALIZE_NGRAM_REPEAT_RATIO_MAX,
)
from app.services.model_backends import CompletionRequest, ModelBackend

logger = logging.getLogger("dejaq.services.context_adjuster")

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

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


# Empirically stops the runaway shape observed in the incident (the
# generalizer regurgitating its own few-shot turn structure as fake
# continuation turns) whenever the loop reuses this literal marker: on the
# captured runaway it fires at offset 350, cutting the loop off before the
# first fake continuation turn. Proven NOT sufficient alone: a
# differently-worded loop (observed: restating a country count with a
# different number each pass) never emits this string and runs to the token
# cap regardless. is_generalization_sane() below is the actual guard; this is
# a cheap, latency-free first line of defense with no downside when it
# doesn't fire.
#
# Deliberately only the separator marker. "ANSWER:" variants were tried and
# removed: the backend matches a stop string anywhere in the generated text,
# so a legitimate quiz/exam-style rewrite that faithfully reproduces the raw
# answer's own "ANSWER: ..." lines would be silently truncated mid-rewrite -
# and a truncated prefix is SHORTER than the raw answer with no repetition,
# so is_generalization_sane() cannot detect it. That trades a rare loop for a
# silently wrong cache entry, which is the exact failure this guard exists to
# prevent.
_GENERALIZE_STOP = ["\n\n\n*****"]

_NGRAM_SIZE = 4


def _ngram_repetition_ratio(text: str, n: int = _NGRAM_SIZE) -> float:
    words = _TOKEN_RE.findall(text.lower())
    if len(words) <= n:
        return 0.0
    grams = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
    counts = Counter(grams)
    repeated = sum(c - 1 for c in counts.values() if c > 1)
    return repeated / len(grams)


def is_generalization_sane(raw_answer: str, generalized: str) -> bool:
    """Store-time safety net for generalize()'s own output.

    Unlike is_topically_consistent() (which gates adjust() against drifting
    from an already-trusted cached answer), this catches generalize() itself
    finishing the real rewrite and then failing to stop: the model loops,
    paraphrasing its own few-shot examples as fake continuation turns, until
    it hits the token cap (incident: dejaq-generalizer-runaway - a 52-char
    real answer produced a 5,456-character loop with no stop). Two
    independent, cheap, stdlib-only signals, each measured against that
    capture plus a fresh 20-query batch (see app/config.py for the numbers
    behind each threshold):
      - a blown length ratio against the raw answer (measured: 104.9x on the
        full runaway, 13.0x on the shorter contained leak), or
      - an elevated word n-gram repetition ratio (measured 0.150 on the
        runaway; catches loops that reword slightly each pass, so no exact
        line or substring repeats - e.g. restating a continent count with a
        different number every loop).

    A third signal - an exact verbatim-repeated line - was tried and removed:
    it fired on neither captured incident (both separator lines are 5 chars,
    below its own length floor), while it did reject ordinary structured
    answers such as two markdown tables sharing a column-separator row,
    silently disabling generalization for the answer shapes LLMs emit most.
    """
    if not generalized.strip():
        return False
    if (
        len(generalized) > GENERALIZE_LENGTH_RATIO_MAX * max(len(raw_answer), 1)
        and len(generalized) > GENERALIZE_LENGTH_ABS_FLOOR
    ):
        return False
    if _ngram_repetition_ratio(generalized) > GENERALIZE_NGRAM_REPEAT_RATIO_MAX:
        return False
    return True


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
                # Few-shot examples must stay inert (no real-world fact in
                # their content): a small instruct model can regurgitate a
                # few-shot's own subject matter instead of conditioning on
                # the real ANSWER. The turn shape below is what teaches
                # tone-stripping; any real fact in it becomes a leak.
                # Example 1: casual → neutral
                {"role": "user", "content": "ANSWER: Yo so basically the mechanism just takes whatever input you give it and spits out an output, no biggie, it does this by running through a fixed set of steps every time!"},
                {"role": "assistant", "content": "The mechanism converts an input value into an output value by applying a fixed sequence of transformation steps."},
                # Example 2: casual → neutral
                {"role": "user", "content": "ANSWER: The little widget thingy is super handy, it just quietly does its own validation step before passing stuff along, no fuss!"},
                {"role": "assistant", "content": "The component performs an internal validation step before forwarding its input for further processing."},
                # Actual answer
                {"role": "user", "content": f"ANSWER: {answer}"},
                ],
                max_tokens=1024,
                # Deterministic: this is a faithful tone-neutralization
                # rewrite, not creative generation, so temperature buys
                # nothing here (see adjust() below for the same reasoning).
                temperature=0,
                stop=_GENERALIZE_STOP,
            )
        )

        latency = (time.time() - start) * 1000
        logger.debug("Generalization completed in %.2f ms", latency)

        if not is_generalization_sane(answer, generalized):
            logger.warning(
                "Generalizer output failed sanity check (raw_len=%d, "
                "generalized_len=%d); storing the raw answer un-generalized instead",
                len(answer), len(generalized),
            )
            return answer

        return generalized

    async def adjust(self, original_query: str, general_answer: str) -> str:
        logger.debug(f"Adjusting response for original query: {original_query}")

        start = time.time()

        adjusted = await self.adjust_backend.complete(
            CompletionRequest(
                model_name=self.adjust_model_name,
                messages=[
                {"role": "system", "content": "Rewrite the ANSWER to match the tone of the QUESTION. Keep all facts. Output only the rewritten answer."},
                # Few-shot examples must stay inert (no real-world fact in
                # their content): a small instruct model can pattern-match on
                # the SHAPE of a request and regurgitate a few-shot's own
                # subject matter instead of conditioning on the real ANSWER,
                # whenever a real QUESTION merely resembles that example's
                # shape. Any example carrying a real-world fact reintroduces
                # this failure mode, so never add one - keep examples about a
                # generic "mechanism" or similar inert subject.
                # Example 1: casual/child tone
                {"role": "user", "content": "QUESTION: explain it like I'm 5\nANSWER: The mechanism converts an input value into an output value by applying a fixed sequence of transformation steps."},
                {"role": "assistant", "content": "Imagine a toy machine! You drop a ball in one side, some fun stuff happens inside, and a different toy pops out the other side! That's what this does, but with information instead of toys!"},
                # Example 2: casual/brief tone
                {"role": "user", "content": "QUESTION: give me the short version\nANSWER: The mechanism converts an input value into an output value by applying a fixed sequence of transformation steps: first validating the input, then transforming it, then producing the output."},
                {"role": "assistant", "content": "It just turns input into output in a few simple steps."},
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
