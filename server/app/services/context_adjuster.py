import asyncio
import logging
import re
import time
from collections import Counter

from app.config import (
    ADJUST_LENGTH_ABS_FLOOR,
    ADJUST_LENGTH_RATIO_MAX,
    ADJUST_NGRAM_REPEAT_RATIO_MAX,
    ADJUST_TIMEOUT_SECONDS,
    ADJUSTER_MIN_TOPIC_OVERLAP,
    GENERALIZE_LENGTH_ABS_FLOOR,
    GENERALIZE_LENGTH_RATIO_MAX,
    GENERALIZE_NGRAM_REPEAT_RATIO_MAX,
    NGRAM_EXEMPT_LENGTH_RATIO,
    OLLAMA_NUM_CTX,
    REWRITE_MAX_TOKENS,
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


def _inherits_baseline_repetition(baseline: str, output: str, absolute_max: float) -> bool:
    """Whether `output`'s repetition can only have come from `baseline`'s own,
    exempting it from the repetition ceiling.

    The repetition ceilings are absolute and measured (0.08, see app/config.py),
    and this is the ONE population they cannot serve: a legitimately templated
    answer is repetitive by construction (a 50-item numbered list of one
    sentence frame measures 0.35-0.48, a 14-week course schedule 0.338), and
    both rewrite prompts REQUIRE every item of it to survive, so a faithful
    rewrite of that whole answer shape scores far past any ceiling low enough
    to catch a real loop.

    Three conditions, and all three are load-bearing:

    - The baseline must ALREADY fail the same ceiling, i.e. carry repetition of
      its own for a rewrite to inherit. Size alone is not enough: a pure
      self-paraphrase loop over ordinary non-repetitive prose can land at the
      baseline's own size (measured on a 657-character prose answer at 0.000:
      loops at 0.877x and 1.102x scoring 0.202-0.208), and exempting those
      reopens the ceiling on the very population it was calibrated against.
    - The sizes must stay close. A loop repeats itself INTO more text than it
      was given (measured on the templated list: a faithful rewrite is 1.18x,
      self-paraphrase loops 2.45x and up), or collapses onto one item and
      repeats that instead (0.56x). Both directions leave the band and face the
      unmodified ceiling.
    - The output may be no more repetitive than the baseline plus one ceiling's
      worth of headroom. Without this the first condition is a binary gate: any
      baseline a hair over the ceiling would exempt an arbitrarily repetitive
      same-size output. Measured on a mildly structured answer - three parallel
      bullets inside ordinary prose, 0.088 - where same-size self-paraphrase
      loops score 0.570-0.618. The headroom is the ceiling itself rather than a
      new constant: "about as repetitive as its source, plus what a clean
      rewrite is allowed outright". The faithful templated rewrite this
      exemption exists for sits at +0.079 against a 0.08 allowance.

    Scaling the ceiling to the baseline's own repetition was tried and removed:
    at 1.5x the baseline it opened a fail-open band on exactly this population,
    where a loop emitting 2-3 further self-paraphrase passes scored 0.508-0.526
    against a 0.527 ceiling while staying far under the length arm's 10x. The
    additive headroom above is bounded in absolute terms, so it cannot widen
    the same way as the baseline's own repetition grows.
    """
    if not baseline:
        return False
    baseline_repetition = _ngram_repetition_ratio(baseline)
    if baseline_repetition <= absolute_max:
        return False
    ratio = len(output) / len(baseline)
    if not 1 / NGRAM_EXEMPT_LENGTH_RATIO <= ratio <= NGRAM_EXEMPT_LENGTH_RATIO:
        return False
    return _ngram_repetition_ratio(output) - baseline_repetition <= absolute_max


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
      - a word n-gram repetition ratio over GENERALIZE_NGRAM_REPEAT_RATIO_MAX
        (measured 0.150 on the runaway; catches loops that reword slightly
        each pass, so no exact line or substring repeats - e.g. restating a
        continent count with a different number every loop), applied unless
        the raw answer was itself repetitive, the rewrite kept its size, and
        the rewrite is no more repetitive than the raw answer itself was, so
        the repetition can only have been inherited rather than invented - see
        _inherits_baseline_repetition().

    A third signal - an exact verbatim-repeated line - was tried and removed:
    it fired on neither captured incident (both separator lines are 5 chars,
    below its own length floor), while it did reject ordinary structured
    answers such as two markdown tables sharing a column-separator row,
    silently disabling generalization for the answer shapes LLMs emit most.

    generalize()'s own max_tokens was raised from 1024 to REWRITE_MAX_TOKENS so
    a long, factual answer stops truncating mid-sentence under the "Keep all
    facts" system prompt - a real raw answer can reach ~3,700 tokens
    (openai_compat.DEFAULT_MAX_TOKENS) and the stored copy is what every future cache hit
    serves, so a truncated one never self-heals. That raise does not weaken
    this guard: the length signal is a proportion of the raw answer's own
    length and the repetition signal a proportion of the output's own n-grams,
    neither tied to the token budget - a longer runway for a loop to run only
    pushes both further past these thresholds, never back under them.
    """
    if not generalized.strip():
        return False
    if (
        len(generalized) > GENERALIZE_LENGTH_RATIO_MAX * max(len(raw_answer), 1)
        and len(generalized) > GENERALIZE_LENGTH_ABS_FLOOR
    ):
        return False
    if (
        _ngram_repetition_ratio(generalized) > GENERALIZE_NGRAM_REPEAT_RATIO_MAX
        and not _inherits_baseline_repetition(
            raw_answer, generalized, GENERALIZE_NGRAM_REPEAT_RATIO_MAX
        )
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
      - a word n-gram repetition ratio over ADJUST_NGRAM_REPEAT_RATIO_MAX,
        which catches a loop that rewords itself each pass and so never
        repeats a literal line. This is the signal that does the real work: a
        runaway is repetitive by construction, whatever it was rewriting. It
        is skipped only when the cached answer was itself repetitive, the
        rewrite kept its size, and the rewrite added no repetition of its own
        (_inherits_baseline_repetition), because the
        system prompt above REQUIRES every bullet and numbered item to
        survive, so a same-size rewrite of a templated answer reproduces that
        template's own repetition (a 50-item list measures 0.35-0.48) -
        without that exemption the prompt would manufacture the very signal
        that discards its output.
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
    if (
        _ngram_repetition_ratio(adjusted) > ADJUST_NGRAM_REPEAT_RATIO_MAX
        and not _inherits_baseline_repetition(
            cached_answer, adjusted, ADJUST_NGRAM_REPEAT_RATIO_MAX
        )
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

        messages = [
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
        ]
        # The rewrite budget, not the request's own (see
        # REWRITE_MAX_TOKENS in app/config.py, the same budget adjust()
        # uses). The system prompt above says "Keep all facts"; a raw
        # miss answer can reach ~3,700 tokens
        # (openai_compat.DEFAULT_MAX_TOKENS),
        # so the old 1024 cap truncated the generalized rewrite of a
        # long answer mid-sentence - and the stored copy is what every
        # future cache hit serves, so a truncated one never self-heals.
        # This role is one of only two that need a window set: num_ctx
        # bounds the prompt as well as the generation, and the prompt
        # here carries the whole answer being rewritten on top of that
        # budget. Left at Ollama's own default, the pair overflows it
        # and the head of the prompt is silently dropped - so the model
        # never sees the tail of the answer it was told to preserve.
        # Deterministic: this is a faithful tone-neutralization
        # rewrite, not creative generation, so temperature buys
        # nothing here (see adjust() below for the same reasoning).
        generalized = await self.generalize_backend.complete(
            CompletionRequest(
                model_name=self.generalize_model_name,
                messages=messages,
                max_tokens=REWRITE_MAX_TOKENS,
                num_ctx=OLLAMA_NUM_CTX,
                temperature=0,
                stop=_GENERALIZE_STOP,
            )
        )

        # The stop string matches anywhere in the generation, including as
        # part of legitimate content (a faithful rewrite of an answer that
        # itself contains a "*****" markdown thematic break after a blank
        # line). done_reason=="stop" cannot tell that apart from the intended
        # runaway-loop trip: Ollama omits the matched stop text from the
        # response either way, and is_generalization_sane() cannot see a
        # truncation, since a truncated rewrite is SHORTER than the raw
        # answer with no elevated repetition - exactly the profile of a
        # clean rewrite. So on a stop-string hit, regenerate once WITHOUT
        # the stop sequence to get the untruncated text and let the actual
        # guard (is_generalization_sane, below) judge it on its merits - a
        # real runaway still fails that guard (see
        # test_rejects_the_real_captured_runaway); legitimate content is no
        # longer cut off at a coincidental marker match.
        if generalized.done_reason == "stop":
            generalized = await self.generalize_backend.complete(
                CompletionRequest(
                    model_name=self.generalize_model_name,
                    messages=messages,
                    max_tokens=REWRITE_MAX_TOKENS,
                    num_ctx=OLLAMA_NUM_CTX,
                    temperature=0,
                )
            )

        latency = (time.time() - start) * 1000
        logger.debug("Generalization completed in %.2f ms", latency)

        # Ollama's own signal, not inferred: is_generalization_sane() cannot
        # see a truncation, since a truncated rewrite is SHORTER than the raw
        # answer with no elevated repetition - exactly the profile of a clean
        # rewrite. This matters more here than anywhere else in the pipeline:
        # whatever generalize() returns is what gets PERSISTED to ChromaDB,
        # so a truncated copy never self-heals - every future cache hit would
        # serve the same cut-off answer. Falls back to the complete raw
        # answer, the same target every other guard in this function falls
        # back to.
        if generalized.done_reason == "length":
            logger.warning(
                "Generalizer output was truncated (done_reason=length, raw_len=%d, "
                "generalized_len=%d); storing the raw answer un-generalized instead",
                len(answer), len(generalized.text),
            )
            return answer

        generalized_text = generalized.text
        if not is_generalization_sane(answer, generalized_text):
            logger.warning(
                "Generalizer output failed sanity check (raw_len=%d, "
                "generalized_len=%d); storing the raw answer un-generalized instead",
                len(answer), len(generalized_text),
            )
            return answer

        return generalized_text

    async def adjust(self, original_query: str, general_answer: str) -> str:
        logger.debug(f"Adjusting response for original query: {original_query}")

        start = time.time()

        completion = self.adjust_backend.complete(
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
                # The rewrite budget, not the request's own (see
                # REWRITE_MAX_TOKENS in app/config.py): the system prompt above
                # requires every section, bullet and named entity to survive,
                # so a full-fidelity rewrite needs at least the budget the
                # stored answer itself occupies. A smaller cap truncates it
                # mid-sentence, and nothing downstream notices - the
                # topic-overlap net passes on a truncated prefix.
                max_tokens=REWRITE_MAX_TOKENS,
                # The other role that needs a window set, for the reason
                # generalize() above records: this prompt carries the whole
                # cached answer on top of the same budget.
                num_ctx=OLLAMA_NUM_CTX,
                # Deterministic: this is a faithful rewrite, not creative
                # generation, so temperature buys nothing here and only made the
                # regurgitation failure above intermittent and hard to reproduce.
                temperature=0,
            )
        )
        # Every other guard in this function is post-hoc: they all need the
        # generation to come back before they can reject it, so none of them
        # bounds how long a waiting user holds the cache-hit path open. That is
        # what this deadline is for (see ADJUST_TIMEOUT_SECONDS in
        # app/config.py) - it fires into the same fallback the other guards
        # use, the complete cached answer.
        try:
            adjusted = await asyncio.wait_for(completion, timeout=ADJUST_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning(
                "Context adjuster timed out after %.1fs (cached_len=%d); "
                "serving the cached answer verbatim instead",
                ADJUST_TIMEOUT_SECONDS, len(general_answer),
            )
            return general_answer

        latency = (time.time() - start) * 1000
        logger.debug("Context adjustment completed in %.2f ms", latency)

        # Same signal generalize() acts on above, for the same reason
        # is_adjustment_sane() below cannot see it: a truncated rewrite is
        # shorter than the cached answer with no elevated repetition. Lower
        # stakes here than in generalize() - this path is per-request, not
        # persisted - but a truncated rewrite is still a worse answer than
        # the complete cached one it would replace, so the same fallback
        # applies.
        if adjusted.done_reason == "length":
            logger.warning(
                "Context adjuster output was truncated (done_reason=length, "
                "cached_len=%d, adjusted_len=%d); serving the cached answer verbatim instead",
                len(general_answer), len(adjusted.text),
            )
            return general_answer

        adjusted_text = adjusted.text
        if not is_adjustment_sane(general_answer, adjusted_text):
            logger.warning(
                "Context adjuster output failed sanity check (cached_len=%d, "
                "adjusted_len=%d); serving the cached answer verbatim instead",
                len(general_answer), len(adjusted_text),
            )
            return general_answer

        if not is_topically_consistent(adjusted_text, general_answer):
            logger.warning(
                "Context adjuster output failed topic-consistency check; "
                "serving cached answer verbatim instead of the drifted rewrite"
            )
            return general_answer

        return adjusted_text
