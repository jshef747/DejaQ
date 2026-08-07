import logging
import re
import time
from collections import Counter

from app.config import (
    ADJUST_LENGTH_ABS_FLOOR,
    ADJUST_LENGTH_RATIO_MAX,
    ADJUST_NGRAM_REPEAT_RATIO_MAX,
    ADJUSTER_MIN_TOPIC_OVERLAP,
    DEFAULT_MAX_TOKENS,
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

# Both rewrite steps size their output budget off the text they were handed,
# not off a fixed constant. DEFAULT_MAX_TOKENS is only the ceiling a request
# gets when the client sends no limit of its own; openai_compat.py applies no
# upper clamp to a client-supplied max_tokens, so a request asking for 8192
# tokens produces a raw answer that a fixed 4096-token rewrite budget would
# truncate mid-sentence - the exact failure raising that cap was meant to end.
# Sized off the specific text in hand, the budget covers it whatever the
# original request asked for. //3 is a deliberately conservative
# chars-per-token estimate (English averages ~4 characters per token, so this
# over-provisions), and the margin covers a faithful rewrite that runs mildly
# longer in different phrasing.
_CHARS_PER_TOKEN = 3
_REWRITE_TOKEN_MARGIN = 512


def _rewrite_token_budget(baseline: str) -> int:
    return max(
        DEFAULT_MAX_TOKENS,
        len(baseline) // _CHARS_PER_TOKEN + _REWRITE_TOKEN_MARGIN,
    )


def _ngram_repetition_ratio(text: str, n: int = _NGRAM_SIZE) -> float:
    words = _TOKEN_RE.findall(text.lower())
    if len(words) <= n:
        return 0.0
    grams = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
    counts = Counter(grams)
    repeated = sum(c - 1 for c in counts.values() if c > 1)
    return repeated / len(grams)


# How much more repetitive than its own input a faithful rewrite may be before
# the repetition reads as a loop. Multiplicative rather than a fixed offset:
# the wordier a rewrite's repeated frame is, the more repetition it inherits in
# absolute terms, and a measured faithful rewrite of a 50-item list ("... served
# as President of the United States from X to Y" restated as "... held the
# office of President of the United States between X and Y") lands 0.079 above
# its source - already at any offset small enough to still catch the captured
# runaways. Against the same pair the ceiling below sits at 0.528, with the
# rewrite at 0.430 and a loop of that same list at 0.783-0.966.
_NGRAM_BASELINE_GROWTH_MAX = 1.5


def _repetition_ceiling(baseline: str, absolute_max: float) -> float:
    """Highest repetition ratio an output rewriting `baseline` may carry.

    Baseline-relative, with the absolute threshold as a floor. An absolute
    ceiling alone cannot separate the two populations: a legitimately templated
    answer is repetitive by construction (a 50-item numbered list of one
    sentence frame measures 0.35-0.48 depending on how much of each item is
    boilerplate, a 14-week course schedule 0.338), and both
    rewrite prompts REQUIRE every item of it to survive, so any ceiling low
    enough to catch a runaway also discards faithful rewrites of that whole
    answer shape. A faithful rewrite inherits its input's repetition; a runaway
    invents repetition the input never had.

    The floor is what keeps the measured incident detection intact: every
    captured runaway rewrote a raw answer with no repetition of its own
    (0.000), so on that population this is exactly the absolute check it
    replaces, and a near-zero baseline cannot scale the ceiling down below it.
    """
    return max(absolute_max, _ngram_repetition_ratio(baseline) * _NGRAM_BASELINE_GROWTH_MAX)


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
      - a word n-gram repetition ratio past _repetition_ceiling() for the raw
        answer (measured 0.150 on the runaway against a raw answer at 0.000;
        catches loops that reword slightly each pass, so no exact line or
        substring repeats - e.g. restating a continent count with a different
        number every loop).

    Both signals are proportions of the raw answer's own shape rather than
    absolute limits, for the same reason: a faithful rewrite inherits what it
    was rewriting. See _repetition_ceiling() for why an absolute repetition
    limit alone cannot separate a templated answer from a loop.

    A third signal - an exact verbatim-repeated line - was tried and removed:
    it fired on neither captured incident (both separator lines are 5 chars,
    below its own length floor), while it did reject ordinary structured
    answers such as two markdown tables sharing a column-separator row,
    silently disabling generalization for the answer shapes LLMs emit most.

    generalize()'s own max_tokens was raised from 1024 to a budget sized off
    the raw answer (_rewrite_token_budget) so a long, factual answer stops
    truncating mid-sentence under the "Keep all facts" system prompt - a real
    raw answer can reach ~3,700 tokens (openai_compat.py:667) and the stored
    copy is what every future cache hit serves, so a truncated one never
    self-heals. That raise does not weaken this guard: both signals are
    proportions of the raw answer's own shape, not tied to the token budget -
    a longer runway for a loop to run only pushes its length ratio and n-gram
    repetition further past these thresholds, never back under them.
    """
    if not generalized.strip():
        return False
    if (
        len(generalized) > GENERALIZE_LENGTH_RATIO_MAX * max(len(raw_answer), 1)
        and len(generalized) > GENERALIZE_LENGTH_ABS_FLOOR
    ):
        return False
    if _ngram_repetition_ratio(generalized) > _repetition_ceiling(
        raw_answer, GENERALIZE_NGRAM_REPEAT_RATIO_MAX
    ):
        return False
    return True


def is_adjustment_sane(cached_answer: str, adjusted: str) -> bool:
    """Serve-time safety net for adjust()'s own output.

    The sibling of is_generalization_sane() above, guarding the same failure
    (the model finishing its rewrite and then looping through paraphrases
    until it hits the token cap) on the synchronous cache-hit path, where
    is_topically_consistent() cannot see it: that check measures how much of
    the CACHED answer's vocabulary survives into the output, so a loop that
    paraphrases the cached answer over and over scores near 1.0 and passes
    clean. Both signals here measure the output against the cached answer
    adjust() was handed:
      - a word n-gram repetition ratio past _repetition_ceiling() for that
        cached answer, which catches a loop that rewords itself each pass and
        so never repeats a literal line. This is the signal that does the real
        work: a runaway invents repetition its input never had, whatever it
        was rewriting. Measured against the cached answer rather than as an
        absolute limit because the system prompt above REQUIRES every bullet
        and numbered item to survive, so a faithful rewrite of a templated
        answer reproduces that template's own repetition (a 50-item list
        measures 0.35-0.48) - against an absolute ceiling the prompt would
        manufacture the very signal that discards its output.
      - a blown length ratio against that same cached answer, as a backstop
        for a loop varied enough to stay under the repetition bar. It applies
        only once the cached answer clears ADJUST_LENGTH_ABS_FLOOR, because a
        short cached answer is a denominator too small to read anything into:
        "explain that in more detail" against a one-line cached answer
        legitimately returns many times its length.

    Length is bounded in one direction only. A tone rewrite legitimately
    shrinks a long cached answer whenever the question asks it to ("give me
    the short version"), and ADJUSTER_MIN_TOPIC_OVERLAP already guards that
    direction; only unbounded growth indicates a runaway.
    """
    if not adjusted.strip():
        return False
    if (
        len(cached_answer) >= ADJUST_LENGTH_ABS_FLOOR
        and len(adjusted) > ADJUST_LENGTH_RATIO_MAX * len(cached_answer)
    ):
        return False
    if _ngram_repetition_ratio(adjusted) > _repetition_ceiling(
        cached_answer, ADJUST_NGRAM_REPEAT_RATIO_MAX
    ):
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
                # Sized to comfortably cover THIS answer (see
                # _rewrite_token_budget above for the identical reasoning
                # adjust() uses). The system prompt above says "Keep all
                # facts"; a raw miss answer can reach ~3,700 tokens
                # (openai_compat.py:667) and more when the client asked for a
                # larger budget, so a fixed cap truncated the generalized
                # rewrite of a long answer mid-sentence - and the stored copy
                # is what every future cache hit serves, so a truncated one
                # never self-heals.
                max_tokens=_rewrite_token_budget(answer),
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
                {"role": "system", "content": "Rewrite the ANSWER to match the tone of the QUESTION. Preserve every fact, name, number, and detail from the ANSWER, no matter how long or how many sections or bullet points it has - only shorten or simplify if the QUESTION explicitly asks for that (e.g. \"give me the short version\", \"explain it simply\"). A QUESTION that just rephrases or repeats the same ask, even in different words, is not a request to shorten. If the ANSWER has sections, bullet points, or numbered items, your rewrite must have the same number of sections, bullet points, or numbered items, each carrying the same information as the original, just reworded - never merge, drop, or summarize any of them unless asked to. Keep every named entity from the ANSWER - every place, event, organization, and date it mentions - in your rewrite. Output only the rewritten answer."},
                # Few-shot examples must stay inert (no real-world fact in
                # their content): a small instruct model can pattern-match on
                # the SHAPE of a request and regurgitate a few-shot's own
                # subject matter instead of conditioning on the real ANSWER,
                # whenever a real QUESTION merely resembles that example's
                # shape. Any example carrying a real-world fact reintroduces
                # this failure mode, so never add one - keep examples about a
                # generic "mechanism" or similar inert subject.
                #
                # Examples 1 and 2 below are deliberate, explicit requests for
                # a simpler/shorter answer - the model needs to see that this
                # is a legitimate reason to drop detail. Examples 3 and 4 are
                # the opposite and equally important: a QUESTION that is
                # merely reworded (no explicit ask for anything shorter or
                # simpler) must keep every step of the ANSWER. Without them, a
                # small model over-generalizes from 1 and 2 and treats ANY
                # casual or terse-sounding QUESTION as a cue to condense -
                # measured directly: with only examples 1 and 2 present, a
                # verbatim repeat of the original QUESTION, phrased with zero
                # tone gap, still triggered the same aggressive compression as
                # an explicit "short version" ask - a real 1757-character
                # cached answer came back at 242 characters with named events
                # dropped. Example 4 specifically mirrors the shape of that
                # answer (headers, bullets, a numbered list): a single
                # short-form example (3) was not enough to override the small
                # model's own tendency to summarize long, structured input,
                # and only adding the same-shape example moved the measured
                # content-word overlap on that case from 0.052 to 0.463. Two
                # minor named entities and one event name are still dropped
                # there - a real remaining gap, not full parity.
                # Example 1: casual/child tone (explicit ask for simple)
                {"role": "user", "content": "QUESTION: explain it like I'm 5\nANSWER: The mechanism converts an input value into an output value by applying a fixed sequence of transformation steps."},
                {"role": "assistant", "content": "Imagine a toy machine! You drop a ball in one side, some fun stuff happens inside, and a different toy pops out the other side! That's what this does, but with information instead of toys!"},
                # Example 2: casual/brief tone (explicit ask for short)
                {"role": "user", "content": "QUESTION: give me the short version\nANSWER: The mechanism converts an input value into an output value by applying a fixed sequence of transformation steps: first validating the input, then transforming it, then producing the output."},
                {"role": "assistant", "content": "It just turns input into output in a few simple steps."},
                # Example 3: reworded, NOT an ask for anything shorter - every
                # step must survive, only the phrasing changes.
                {"role": "user", "content": "QUESTION: wait, why does that even happen in the first place?\nANSWER: The mechanism converts an input value into an output value by applying a fixed sequence of transformation steps: first validating the input, then transforming it, then producing the output."},
                {"role": "assistant", "content": "That happens because the mechanism converts an input value into an output value through a fixed sequence of transformation steps: it first validates the input, then transforms it, and finally produces the output."},
                # Example 4: reworded, NOT an ask for anything shorter, and the
                # ANSWER is long and structured - every factor, bullet, and
                # numbered step must survive.
                {"role": "user", "content": (
                    "QUESTION: why does it end up behaving like that though?\n"
                    "ANSWER: The mechanism exhibits this behavior for several interconnected reasons.\n\n"
                    "**Core factors:**\n"
                    "* **Input variability:** the mechanism receives inputs of different shapes, so it must validate each one before proceeding.\n"
                    "* **Sequential processing:** each stage depends on the output of the previous stage, so an error early in the sequence propagates forward.\n"
                    "* **Resource constraints:** the mechanism operates within a fixed capacity, so it queues excess work rather than dropping it.\n\n"
                    "**Sequence of steps:**\n"
                    "1. The mechanism receives an input and validates its shape.\n"
                    "2. It transforms the input according to a fixed rule set.\n"
                    "3. It produces an output and logs the transformation for later inspection.\n\n"
                    "In short, the behavior results from how input validation, sequential dependency, and resource limits interact within the mechanism's fixed pipeline."
                )},
                {"role": "assistant", "content": (
                    "That happens because of a few things working together inside the mechanism.\n\n"
                    "**Core factors:**\n"
                    "* **Input variability:** it gets inputs of different shapes, so it has to validate each one before moving on.\n"
                    "* **Sequential processing:** each stage depends on the one before it, so an early error carries forward through the rest.\n"
                    "* **Resource constraints:** it only has a fixed amount of capacity, so extra work gets queued instead of dropped.\n\n"
                    "**Sequence of steps:**\n"
                    "1. It receives an input and validates its shape.\n"
                    "2. It transforms the input using a fixed set of rules.\n"
                    "3. It produces an output and logs the transformation for later inspection.\n\n"
                    "So basically, it's the combination of input validation, steps depending on each other in order, and limited resources that causes this."
                )},
                # Actual query
                {"role": "user", "content": f"QUESTION: {original_query}\nANSWER: {general_answer}"},
                ],
                # Sized to comfortably cover THIS cached answer: the system
                # prompt above requires every section, bullet and named entity
                # to survive, so a full-fidelity rewrite needs at least the
                # budget the stored answer itself occupies. A smaller cap
                # truncates it mid-sentence, and nothing downstream notices -
                # the topic-overlap net passes on a truncated prefix.
                max_tokens=_rewrite_token_budget(general_answer),
                # Deterministic: this is a faithful rewrite, not creative
                # generation, so temperature buys nothing here and only made the
                # regurgitation failure above intermittent and hard to reproduce.
                temperature=0,
            )
        )

        latency = (time.time() - start) * 1000
        logger.debug("Context adjustment completed in %.2f ms", latency)

        if not is_adjustment_sane(general_answer, adjusted):
            logger.warning(
                "Context adjuster output failed sanity check (cached_len=%d, "
                "adjusted_len=%d); serving the cached answer verbatim instead",
                len(general_answer), len(adjusted),
            )
            return general_answer

        if not is_topically_consistent(adjusted, general_answer):
            logger.warning(
                "Context adjuster output failed topic-consistency check; "
                "serving cached answer verbatim instead of the drifted rewrite"
            )
            return general_answer

        return adjusted
