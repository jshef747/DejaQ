import asyncio
import re

import pytest

from app.config import (
    ADJUST_LENGTH_ABS_FLOOR,
    ADJUST_LENGTH_RATIO_MAX,
    DEFAULT_MAX_TOKENS,
)
from app.services.context_adjuster import (
    ContextAdjusterService,
    _GENERALIZE_STOP,
    _ngram_repetition_ratio,
    is_adjustment_sane,
    is_generalization_sane,
    is_topically_consistent,
)

# Real cached answer/question pair from the diagnosed bug: a real DejaQ answer
# (Kubernetes canary deployments) paired with the near-verbatim assistant turn
# of the few-shot that used to leak into unrelated cache hits.
CANARY_ANSWER = (
    "A canary deployment rolls out a new version of an application to a small "
    "subset of traffic first, so problems are caught before a full rollout."
)
LEAKED_PHOTOSYNTHESIS_ANSWER = (
    "Photosynthesis is the biochemical process by which plants, algae, and certain "
    "bacteria convert light energy into chemical energy. During this process, carbon "
    "dioxide and water are transformed into glucose and oxygen through light-dependent "
    "and light-independent reactions within the chloroplasts."
)

# An ordinary templated answer - the shape a flat n-gram repetition ceiling
# cannot tell apart from a loop. Every item restates one sentence frame, so the
# answer is repetitive by construction while being a perfectly good answer to
# "list every president with their term". Both rewrite prompts REQUIRE every
# numbered item to survive, so a faithful rewrite inherits that repetition.
TEMPLATED_LIST_ANSWER = "\n".join(
    f"{i + 1}. Person {i + 1} served as President of the United States from "
    f"{1789 + i * 4} to {1793 + i * 4}."
    for i in range(50)
)
TEMPLATED_LIST_REWRITE = "\n".join(
    f"{i + 1}. Person {i + 1} held the office of President of the United States "
    f"between {1789 + i * 4} and {1793 + i * 4}."
    for i in range(50)
)


class TestGeneralize:
    pytestmark = pytest.mark.gemma_e2b

    def test_strips_casual_tone(self, context_adjuster_service):
        result = asyncio.run(context_adjuster_service.generalize(
            "Yo, so basically gravity is like the Earth just pulling stuff down, ya know?"
        ))
        assert len(result) > 0
        assert "gravity" in result.lower() or "force" in result.lower()

    def test_neutral_input_passes_through(self, context_adjuster_service):
        neutral = "Photosynthesis is the process by which plants convert light energy into chemical energy."
        result = asyncio.run(context_adjuster_service.generalize(neutral))
        assert len(result) > 0
        assert "photosynthesis" in result.lower()

    def test_returns_nonempty(self, context_adjuster_service):
        result = asyncio.run(context_adjuster_service.generalize("The capital of France is Paris!"))
        assert isinstance(result, str)
        assert len(result.strip()) > 0


class TestAdjust:
    pytestmark = pytest.mark.qwen_1_5b

    def test_matches_casual_tone(self, context_adjuster_service):
        result = asyncio.run(context_adjuster_service.adjust(
            original_query="explain gravity like I'm 5",
            general_answer="Gravity is a fundamental force of attraction between objects with mass.",
        ))
        assert len(result) > 0

    def test_matches_formal_tone(self, context_adjuster_service):
        result = asyncio.run(context_adjuster_service.adjust(
            original_query="Provide a detailed analysis of photosynthesis",
            general_answer="Photosynthesis is how plants make food from sunlight.",
        ))
        assert len(result) > 0

    def test_returns_nonempty(self, context_adjuster_service):
        result = asyncio.run(context_adjuster_service.adjust(
            original_query="what is gravity",
            general_answer="Gravity is a force.",
        ))
        assert isinstance(result, str)
        assert len(result.strip()) > 0

    def test_repeated_calls_stay_topically_consistent(self, context_adjuster_service):
        """The failure this guards against is nondeterministic (temp was 0.3 in
        the buggy version); a single pass proves nothing. Repeat a real call
        against the real model several times and verify every output either
        stays on-topic or the safety net would have caught it, never both
        silently drifting AND passing the check."""
        for _ in range(8):
            result = asyncio.run(context_adjuster_service.adjust(
                original_query="provide a detailed analysis of this",
                general_answer=CANARY_ANSWER,
            ))
            assert is_topically_consistent(result, CANARY_ANSWER), (
                f"drifted output slipped past the safety net: {result!r}"
            )


class _FakeBackend:
    """Records every CompletionRequest it receives and returns a canned reply."""

    def __init__(self, reply: str):
        self.reply = reply
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return self.reply


class TestAdjustSafetyNet:
    """Deterministic tests for the post-hoc fallback and the requests both
    functions send, no Ollama required."""

    pytestmark = pytest.mark.no_model

    def test_falls_back_to_cached_answer_on_topic_drift(self):
        backend = _FakeBackend(LEAKED_PHOTOSYNTHESIS_ANSWER)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.adjust("provide a detailed analysis", CANARY_ANSWER))

        assert result == CANARY_ANSWER

    def test_passes_through_a_consistent_rewrite(self):
        on_topic = "A canary deployment ships a new version to a small slice of traffic before a full rollout."
        backend = _FakeBackend(on_topic)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert result == on_topic

    def test_sends_temperature_zero(self):
        backend = _FakeBackend("A canary deployment ships to a small slice of traffic first.")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert backend.requests[0].temperature == 0

    def test_generalize_sends_temperature_zero(self):
        backend = _FakeBackend("some reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(CANARY_ANSWER))

        assert backend.requests[0].temperature == 0

    def test_generalize_can_reproduce_a_maximally_sized_answer(self):
        """generalize()'s system prompt says 'Keep all facts', so its output
        budget must match what a raw miss answer can reach (~3,700 tokens
        measured, openai_compat.py:667) - a smaller cap truncates the stored
        rewrite mid-sentence, and a truncated STORED answer never self-heals:
        it is what every future cache hit serves."""
        backend = _FakeBackend("The mechanism converts an input into an output.")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(CANARY_ANSWER))

        assert backend.requests[0].max_tokens == DEFAULT_MAX_TOKENS

    def test_adjust_can_reproduce_a_maximally_sized_answer(self):
        """The adjust() system prompt requires every section, bullet and named
        entity to survive, so its output budget must match the one the raw
        answer was generated under. A smaller cap truncates a long stored
        answer mid-sentence, and nothing downstream catches it: the backend
        ignores done_reason and the topic-overlap net passes on a truncated
        prefix."""
        backend = _FakeBackend("A canary deployment ships to a small slice of traffic first.")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert backend.requests[0].max_tokens == DEFAULT_MAX_TOKENS

    def test_generalize_budget_covers_an_answer_larger_than_the_default_cap(self):
        """DEFAULT_MAX_TOKENS is only the ceiling a request gets when the
        client sends no limit of its own - openai_compat.py applies no upper
        clamp to a client-supplied max_tokens, so a request asking for 8192
        tokens produces a raw answer a fixed 4096-token rewrite budget would
        truncate mid-sentence again, and the truncated copy is what every
        future cache hit serves. The budget has to track the answer in hand."""
        oversized = "The mechanism converts an input into an output. " * 1200
        backend = _FakeBackend("short reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(oversized))

        budget = backend.requests[0].max_tokens
        assert budget > DEFAULT_MAX_TOKENS
        assert budget >= len(oversized) / 4

    def test_adjust_budget_covers_a_cached_answer_larger_than_the_default_cap(self):
        """The identical gap on the serve-time side: a stored answer can
        exceed DEFAULT_MAX_TOKENS whenever the request that produced it asked
        for more, and adjust() must be able to reproduce all of it."""
        oversized = "The mechanism converts an input into an output. " * 1200
        backend = _FakeBackend("short reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.adjust("explain that in detail", oversized))

        budget = backend.requests[0].max_tokens
        assert budget > DEFAULT_MAX_TOKENS
        assert budget >= len(oversized) / 4


class TestIsTopicallyConsistent:
    """Pure unit tests for the lexical overlap check, no Ollama required."""

    pytestmark = pytest.mark.no_model

    def test_total_topic_drift_is_rejected(self):
        assert not is_topically_consistent(LEAKED_PHOTOSYNTHESIS_ANSWER, CANARY_ANSWER)

    def test_faithful_eli5_rewrite_is_accepted(self):
        cached = "Gravity is a fundamental force of attraction between objects with mass."
        eli5 = (
            "Imagine you have a ball. When you throw it up, it comes back down! "
            "That's because the Earth is really big and pulls everything toward it. "
            "That pulling is called gravity!"
        )
        assert is_topically_consistent(eli5, cached)

    def test_faithful_terse_rewrite_is_accepted(self):
        assert is_topically_consistent("It's Paris!", "The capital of France is Paris.")

    def test_faithful_expanded_rewrite_is_accepted(self):
        cached = "Postgres uses MVCC to let readers and writers avoid blocking each other."
        expanded = (
            "PostgreSQL employs Multi-Version Concurrency Control (MVCC), which allows "
            "readers and writers to operate without blocking one another by keeping "
            "multiple versions of each row."
        )
        assert is_topically_consistent(expanded, cached)

    def test_empty_cached_answer_never_blocks(self):
        assert is_topically_consistent(LEAKED_PHOTOSYNTHESIS_ANSWER, "")

    def test_another_unrelated_pair_is_rejected(self):
        cached = "Kubernetes uses etcd as its cluster state store, replicated via the Raft protocol."
        drifted = "The French Revolution began in 1789 amid widespread economic inequality and famine."
        assert not is_topically_consistent(drifted, cached)


class TestOverlapThresholdCalibration:
    """Regression guard for the ADJUSTER_MIN_TOPIC_OVERLAP retune, expressed as
    the two populations measured in the safety-net threshold sweep: on-topic
    rewrites that legitimately condense a long cached answer down to a handful
    of shared nouns must be ACCEPTED, drifted output that survives on one
    coincidental word or none must still be REJECTED.

    None of these assert on the threshold constant, but they do bracket it. The
    cached answer below has 58 content words, so the four cases score 0.0000 and
    0.0172 (rejected) against 0.0345 and 0.0862 (accepted): the class passes
    only while the threshold sits in (0.0172, 0.0345], and fails for any retune
    outside that window. The measured decision gap - 0.0185, the highest overlap
    of any genuine drift catch, to 0.0229, the lowest of any false positive -
    lies inside it, so a future retune that leaves the gap breaks a test here
    rather than passing silently."""

    pytestmark = pytest.mark.no_model

    _LONG_CACHED_ANSWER = (
        "A durable message queue typically guarantees at-least-once delivery, "
        "which means a consumer must be prepared to see the same message "
        "arrive more than once after a crash, a network retry, or a "
        "rebalance. The standard fix is to make message handling idempotent: "
        "attach a unique identifier to every message at publish time, and "
        "before processing a message, check a durable store of "
        "previously-seen identifiers. If the identifier has already been "
        "recorded, skip processing and simply re-acknowledge the message. If "
        "it has not been seen, record it and process the message inside the "
        "same transaction so a crash between the two steps cannot cause a "
        "duplicate to slip through. This turns delivery that is merely "
        "at-least-once into processing that behaves as exactly-once from the "
        "consumer perspective."
    )

    def test_correct_short_condensation_of_long_answer_is_accepted(self):
        condensed = (
            "Give each message a unique identifier and record it once "
            "handled, so a repeat delivery is recognized and skipped instead "
            "of processed twice."
        )
        assert is_topically_consistent(condensed, self._LONG_CACHED_ANSWER)

    def test_terse_condensation_sharing_two_words_is_accepted(self):
        """0.0345 - the tightest accepted case, just above the 0.0229 floor of
        the measured false-positive population. Fails if the threshold is ever
        raised back past a two-word overlap."""
        terse = (
            "Stamp each message with an identifier, save it, and ignore "
            "anything that shows up twice."
        )
        assert is_topically_consistent(terse, self._LONG_CACHED_ANSWER)

    def test_regurgitated_placeholder_sharing_one_word_is_rejected(self):
        """0.0172 - the loosest rejected case, just under the 0.0185 ceiling of
        the measured genuine-catch population. This is the real post-#17 drift
        shape (q154 in the report): the adjuster regurgitates its own inert
        few-shot instead of rewriting the cached answer, and one content word
        ('steps') coincidentally survives. Fails if the threshold is ever
        lowered to where a single incidental word rescues drifted output."""
        regurgitated_few_shot = (
            "The mechanism converts an input value into an output value by "
            "applying a fixed sequence of transformation steps."
        )
        assert not is_topically_consistent(regurgitated_few_shot, self._LONG_CACHED_ANSWER)

    def test_rewrite_sharing_no_content_words_is_rejected(self):
        off_topic = (
            "A red panda spends most of its day resting in trees and mainly "
            "eats bamboo shoots, though it is technically a carnivore."
        )
        assert not is_topically_consistent(off_topic, self._LONG_CACHED_ANSWER)


class TestNoContentBearingFewShot:
    """Regression guard: no few-shot example in either adjust() or its sibling
    generalize() may carry a real-world fact a small model could regurgitate
    verbatim - neither the photosynthesis/Paris examples that caused the
    original leak nor a new one. This is the test that fails if someone adds
    another real-world example later."""

    pytestmark = pytest.mark.no_model

    _MARKERS = ["paris", "france", "gravity", "photosynthesis", "eiffel", "croissant"]
    _LEAKING_SNIPPETS = [
        "provide a detailed analysis of photosynthesis",
        "Photosynthesis is how plants make food from sunlight",
        "biochemical process by which plants, algae, and certain bacteria",
        "Photosynthesis is the process by which plants convert light energy into chemical energy, producing glucose and oxygen from carbon dioxide and water.",
    ]
    _DENYLIST = [rf"\b{marker}\b" for marker in _MARKERS] + [
        re.escape(snippet.lower()) for snippet in _LEAKING_SNIPPETS
    ]

    @staticmethod
    def _assert_no_content(messages):
        all_content = " ".join(m["content"] for m in messages).lower()
        for pattern in TestNoContentBearingFewShot._DENYLIST:
            assert not re.search(pattern, all_content), (
                f"content-bearing few-shot resurfaced: {pattern!r}"
            )

    def test_adjust_prompt_has_no_content(self):
        backend = _FakeBackend("some reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        self._assert_no_content(backend.requests[0].messages)

    def test_generalize_prompt_has_no_content(self):
        backend = _FakeBackend("some reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(CANARY_ANSWER))

        self._assert_no_content(backend.requests[0].messages)


class TestIsGeneralizationSane:
    """Pure unit tests for the generalize() store-time safety net (incident:
    dejaq-generalizer-runaway), no Ollama required. RUNAWAY_GENERALIZED_ANSWER
    and MILD_LEAK_GENERALIZED_ANSWER are not synthetic examples - they are the
    real, byte-for-byte text captured from the live incident and its
    reproduction. The first is the full 5,456-character loop that never
    stopped; the second is a shorter, contained leak (415 characters) where
    the model prepended a numbered list regurgitating its own few-shot
    content before finally answering. The second case matters because it is
    NOT caught by a naive "ANSWER:"/"*****" substring count (it contains
    neither marker) - only the length ratio catches it, which is why the
    guard has more than one signal."""

    pytestmark = pytest.mark.no_model

    RAW_ANSWER = "The biggest country in Europe by area is **Russia**."
    RUNAWAY_GENERALIZED_ANSWER = (
        "Indeed, the largest country by land area in Europe is Russia. It spans Eastern Europe and northern Asia, encompasseating vast territories with diverse geography ranging from arctic tundra to subtropical regions. Despite its size, a significant portion of Russia' extraterritorial territory lies outside Europe proper due to parts extending into Asia.\n"
        "\n"
        "\n"
        "*****\n"
        "ANSWER: The primary mechanism by which the system generates output is through executing a predetermined sequence of operations on input data consistently each time it processes information. \n"
        "\n"
        "The component under discussion performs an internal validation process before transmitting its input for further handling, ensuring that only properly formatted or relevant data proceeds in the workflow without any unnecessary commentary or embellishment.\n"
        "\n"
        "\n"
        "*****\n"
        "ANSWER: The largest country by land area within Europe is Russia, covering a vast expanse of territory across both European and Asian continents. This nation boasts an extensive range of climates from arctic conditions to subtropical zones due to its immense geographical spread that extends into Asia as well. Notably, the majority of Russian mainland lies in Europe when considering territorial boundaries within this continent alone.\n"
        "\n"
        "\n"
        "*****\n"
        "ANSWER: The system consistently produces output by methodically applying a predefined series of operations on input data each time it is engaged with. \n"
        "\n"
        "The component being referred to has an integrated validation stage that meticulously checks the integrity and relevance of its inputs before they are sent forward in any processing pipeline, ensuring seamless continuation without additional commentary or unnecessary embellishment for clarity's sake.\n"
        "\n"
        "\n"
        "*****\n"
        "ANSWER: The largest country by land area within Europe is Russia, which spans a significant portion of the continent and extends into parts of Asia as well due to its vast geographical expanse that straddles both continents. This nation features an array of climates from arctic conditions in the north to subtropical regions influenced by Black Sea's warm waters near its southern border, reflecting Europe’s diverse environmental tapestry within this continent alone.\n"
        "\n"
        "ANSWER: The system reliably generates output through a consistent application of predefined operational steps on input data each time it is activated or receives new information to process. \n"
        "\n"
        "The component in question has an embedded validation mechanism that rigorously assesses the quality and relevance of its inputs before they are advanced, ensuring efficient processing within any given system by maintaining a streamlined flow without extraneous commentary for clarity's sake. This internal check is crucial to ensure data integrity prior to further handling or analysis in various systems across different sectors including technology, environmental monitoring and administrative procedures among others.\n"
        "\n"
        "\n"
        "*****\n"
        "ANSWER: The system consistently produces output by methodically applying a predefined series of operations on input data each time it processes information. \n"
        "\n"
        "The component under discussion performs an internal validation process before transmitting its inputs for further processing to ensure the integrity and relevance, thereby maintaining efficiency in handling within any given workflow or pipeline without extraneous commentary that could potentially complicate understanding or interpretation. This feature is particularly beneficial across various systems where clarity of data input can significantly impact outcomes—from technological applications like machine learning algorithms requiring clean datasets to administrative procedures involving sensitive information processing, ensuring accuracy and reliability in the subsequent stages of workflows within these domains.\n"
        "\n"
        "ANSWER: Russia stands as the largest country by land area entirely situated on European soil, with its expansive territory encompassing a wide range of climates from arctic tundra to subtropical regions influenced partly due to Black Sea's warm waters near southern borders—a testament to Europe’s diverse environmental landscape. This vast nation not only dominates the geographical space within European boundaries but also extends into Asia, reflective of its significant transcontinental span that straddles both continents and contributes to a complex interplay between different climatic zones across these regions.\n"
        "\n"
        "ANSWER: The system reliably generates output through methodically applying predefined operational steps on input data each time it processes information for further analysis or action, ensuring consistency in its functioning irrespective of the nature and source of incoming data. \n"
        "\n"
        "The component under discussion performs an internal validation process before transmitting inputs to subsequent stages—a critical feature that guarantees integrity checks are conducted upfront which helps maintain a streamlined flow within any given system or pipeline, thereby ensuring efficiency in handling diverse datasets ranging from environmental readings requiring clean and accurate data for climate modeling purposes through administrative procedures involving sensitive information processing. This internal validation mechanism is beneficial across various systems where clarity of input can significantly impact outcomes—from technological applications like machine learning algorithms that require pristine, uncorrupted training sets to b"
    )

    MILD_RAW_ANSWER = "The capital of Russia is Moscow."
    MILD_LEAK_GENERALIZED_ANSWER = (
        "Correct, the capital city of Russia is indeed Moscow.\n"
        "\n"
        "---\n"
        "\n"
        "**Rewritten Answers with Neutral Tone and Facts Only:\n"
        "\n"
        "1. The mechanism processes an input by executing a predetified set of steps to produce an output consistently every time it operates.\n"
        "2. This component includes an internal validation phase before transmitting its data for subsequent procedures.\n"
        "3. Moscow is recognized as the capital city of Russia."
    )

    def test_rejects_the_real_captured_runaway(self):
        assert not is_generalization_sane(self.RAW_ANSWER, self.RUNAWAY_GENERALIZED_ANSWER)

    def test_rejects_the_real_captured_mild_leak(self):
        """Neither 'ANSWER:' nor '*****' appears in this text - a plain
        marker-substring count would miss it. The length ratio (415/32 =
        13.0x, above the 10x threshold) is what catches it."""
        assert "ANSWER:" not in self.MILD_LEAK_GENERALIZED_ANSWER
        assert "*****" not in self.MILD_LEAK_GENERALIZED_ANSWER
        assert not is_generalization_sane(self.MILD_RAW_ANSWER, self.MILD_LEAK_GENERALIZED_ANSWER)

    def test_rejects_the_real_captured_runaway_given_more_room_to_run(self):
        """generalize()'s max_tokens moved from 1024 to DEFAULT_MAX_TOKENS
        (~4x more budget) so a long, factual answer stops truncating. This
        proves that does not weaken the guard: take the real captured
        incident text (which ran to completion at the OLD 1024-token cap) and
        extend it with more passes of its own self-paraphrasing, simulating
        the same loop given the extra room the new cap allows. Both the
        length ratio and the n-gram repetition signal only get MORE
        pronounced with more room to loop, never less - a longer runway makes
        a runaway easier to catch, not harder."""
        extended = self.RUNAWAY_GENERALIZED_ANSWER + (
            "\n\n" + self.RUNAWAY_GENERALIZED_ANSWER[len(self.RUNAWAY_GENERALIZED_ANSWER) // 2:]
        ) * 3
        assert len(extended) > len(self.RUNAWAY_GENERALIZED_ANSWER) * 2
        assert _ngram_repetition_ratio(extended) > _ngram_repetition_ratio(self.RUNAWAY_GENERALIZED_ANSWER)
        assert not is_generalization_sane(self.RAW_ANSWER, extended)

    def test_accepts_a_faithful_clean_rewrite(self):
        clean = "The largest country in Europe by area is Russia."
        assert is_generalization_sane(self.RAW_ANSWER, clean)

    def test_accepts_the_highest_ratio_measured_on_a_clean_case(self):
        """8.0x - the highest length ratio seen on any of the 15 clean cases
        in the incident's frequency batch (a legitimate elaboration on '206
        bones' with supporting detail). Fails if the ratio threshold is ever
        tightened below this."""
        raw = "There are **206** bones in the adult human body."
        legitimate = (
            "Indeed, there are exactly 206 bones found in a typical adult "
            "human skeleton. This count includes all the major and minor "
            "structures that provide support and protection for the vital "
            "organs and enable mobility."
        )
        assert len(legitimate) / len(raw) < 8.1
        assert is_generalization_sane(raw, legitimate)

    def test_rejects_verbatim_repeated_content_below_the_length_ratio(self):
        """A short loop that never blows the length ratio (1.7x here) is
        still caught, by the n-gram repetition signal alone."""
        raw = "Mercury is the smallest planet in the solar system."
        repeated = (
            "Mercury is the smallest planet.\n\n*****\n\nMercury is the smallest planet.\n\n*****\n\nDone."
        )
        assert len(repeated) / len(raw) < 2.0
        assert not is_generalization_sane(raw, repeated)

    def test_accepts_structured_content_that_repeats_a_table_separator_row(self):
        """Two tables with different headers legitimately share an identical
        column-separator row. The removed repeated-line signal rejected this
        shape outright; the n-gram ratio correctly reads 0.0 on it, since
        nothing but table punctuation repeats."""
        raw = "List the storage limits and the retention windows for the two plans."
        answer = (
            "Storage limits:\n\n"
            "| Plan | Included storage |\n"
            "|--------|------------------|\n"
            "| Basic | 20 GB |\n| Pro | 200 GB |\n\n"
            "Retention windows:\n\n"
            "| Tier | Backup retention |\n"
            "|--------|------------------|\n"
            "| Basic | 7 days |\n| Pro | 90 days |"
        )
        assert is_generalization_sane(raw, answer)

    def test_rejects_a_pathologically_short_raw_answer_expanded_into_a_leak(self):
        """The 'Au' case from the incident's frequency batch: a 2-character
        raw answer expanded into hundreds of characters of unrelated leak."""
        assert not is_generalization_sane("Au", "Acknowledged. " * 40)

    def test_short_raw_answer_with_a_modest_elaboration_is_accepted(self):
        """The absolute length floor exists for exactly this case: a
        correct one-sentence rewrite of a two-character raw answer would
        otherwise trip an enormous ratio purely from the tiny denominator."""
        assert is_generalization_sane("Au", "The chemical symbol for gold is Au.")

    def test_accepts_a_faithful_rewrite_of_an_already_templated_answer(self):
        """The population a flat repetition ceiling cannot serve: the raw
        answer is repetitive by construction, so a faithful rewrite of it is
        too. Rejecting this stores the answer un-generalized, keeping the
        asker's tone in the cache - which is what generalization exists to
        remove."""
        assert _ngram_repetition_ratio(TEMPLATED_LIST_ANSWER) > 0.3
        assert _ngram_repetition_ratio(TEMPLATED_LIST_REWRITE) > 0.3
        assert is_generalization_sane(TEMPLATED_LIST_ANSWER, TEMPLATED_LIST_REWRITE)

    def test_rejects_a_loop_even_when_the_raw_answer_is_itself_templated(self):
        """The other half of the same rule: scaling the ceiling to the raw
        answer must not hand a repetitive input a free pass. This loop restates
        one item of the list over and over - under the length ratio (0.6x) and
        past the scaled ceiling on repetition alone."""
        looped = "Person 1 served as President of the United States from 1789 to 1793. " * 30

        assert len(looped) < len(TEMPLATED_LIST_ANSWER)
        assert not is_generalization_sane(TEMPLATED_LIST_ANSWER, looped)


class TestGeneralizeSafetyNet:
    """Wiring tests: prove generalize() itself falls back to the raw answer
    when the backend returns corrupted output, not just that the pure
    is_generalization_sane() function would reject it in isolation. This is
    the regression test for the incident: it fails if the guard is removed
    from generalize(), using the real captured corruption as the input."""

    pytestmark = pytest.mark.no_model

    def test_falls_back_to_raw_answer_on_the_real_captured_runaway(self):
        backend = _FakeBackend(TestIsGeneralizationSane.RUNAWAY_GENERALIZED_ANSWER)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.generalize(TestIsGeneralizationSane.RAW_ANSWER))

        assert result == TestIsGeneralizationSane.RAW_ANSWER

    def test_falls_back_to_raw_answer_on_the_real_captured_mild_leak(self):
        backend = _FakeBackend(TestIsGeneralizationSane.MILD_LEAK_GENERALIZED_ANSWER)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.generalize(TestIsGeneralizationSane.MILD_RAW_ANSWER))

        assert result == TestIsGeneralizationSane.MILD_RAW_ANSWER

    def test_passes_through_a_sane_rewrite_unchanged(self):
        clean = "The capital city of Russia is Moscow."
        backend = _FakeBackend(clean)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.generalize("The capital of Russia is Moscow."))

        assert result == clean

    def test_sends_the_stop_sequence(self):
        backend = _FakeBackend("some reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize("The capital of Russia is Moscow."))

        assert backend.requests[0].stop == _GENERALIZE_STOP

    def test_no_stop_marker_can_truncate_a_legitimate_rewrite(self):
        """A stop string is matched anywhere in the generated text, so a
        marker that occurs in ordinary answer content (a quiz answer key's
        own 'ANSWER:' lines) would silently truncate a faithful rewrite into
        a shorter, non-repetitive prefix that is_generalization_sane() cannot
        detect. Only the few-shot separator shape is safe to stop on."""
        assert _GENERALIZE_STOP == ["\n\n\n*****"]

        quiz_rewrite = (
            "1. What is the capital of France?\nANSWER: Paris\n"
            "2. What is the capital of Japan?\nANSWER: Tokyo"
        )
        assert not any(marker in quiz_rewrite for marker in _GENERALIZE_STOP)

    def test_the_stop_marker_cuts_the_real_runaway_before_its_fake_turns(self):
        """On the captured runaway the separator marker appears at offset 350,
        ahead of every regurgitated continuation turn, so the stop alone
        truncates it back to the correct rewrite."""
        runaway = TestIsGeneralizationSane.RUNAWAY_GENERALIZED_ANSWER
        cut = runaway.index(_GENERALIZE_STOP[0])

        assert cut == 350
        assert "ANSWER:" not in runaway[:cut]
        assert is_generalization_sane(TestIsGeneralizationSane.RAW_ANSWER, runaway[:cut])


class TestIsAdjustmentSane:
    """Pure unit tests for the adjust() serve-time safety net, the sibling of
    is_generalization_sane() above. adjust() carries no stop string (its
    few-shots are chat turns, with no separator marker to stop on) and runs at
    DEFAULT_MAX_TOKENS on the synchronous cache-hit path, so this guard is the
    only bound on a runaway rewrite reaching a waiting user."""

    pytestmark = pytest.mark.no_model

    CACHED = (
        "A canary deployment rolls out a new version to a small subset of "
        "traffic first, so problems are caught before a full rollout."
    )

    def test_the_shape_topic_overlap_is_blind_to_is_rejected(self):
        """The case this guard exists for: a loop that paraphrases the CACHED
        answer over and over. Every repetition is drawn from the cached
        answer's own vocabulary, so is_topically_consistent() scores it at the
        maximum and passes it clean - only the repetition signal catches it."""
        looped = (
            "A canary deployment rolls out a new version to a small subset of traffic first. "
            * 12
        )

        assert is_topically_consistent(looped, self.CACHED)
        assert not is_adjustment_sane(self.CACHED, looped)

    def test_rejects_a_reworded_loop_that_never_repeats_a_literal_line(self):
        """The runaway shape from the generalizer incident: each pass rewords
        itself, so no line or substring repeats exactly and only the word
        4-gram ratio sees it."""
        reworded_loop = (
            "A canary deployment sends a new version to a small slice of traffic first. "
            "A canary deployment sends a new version to a small share of traffic first. "
            "A canary deployment sends a new version to a small portion of traffic first. "
            "A canary deployment sends a new version to a small fraction of traffic first. "
            "A canary deployment sends a new version to a small segment of traffic first."
        )

        assert reworded_loop.count("A canary deployment sends a new version to a small slice") == 1
        assert not is_adjustment_sane(self.CACHED, reworded_loop)

    def test_rejects_a_loop_from_a_short_cached_answer(self):
        """The length ratio is not consulted at all on a baseline this short
        (see ADJUST_LENGTH_ABS_FLOOR), so the repetition signal is the whole
        defence here - which is the point: a runaway is repetitive by
        construction, whatever length it was rewriting."""
        looped = "Acknowledged. " * 40

        assert len("It's Paris!") < ADJUST_LENGTH_ABS_FLOOR
        assert not is_adjustment_sane("It's Paris!", looped)

    def test_rejects_unbounded_growth_the_repetition_signal_would_miss(self):
        """The backstop the length ratio exists for: output long enough to be
        a runaway but varied enough that no word 4-gram repeats at all, over a
        cached answer past the floor. Fails if the ratio arm is ever dropped
        or gated so tightly that it stops firing."""
        cached = self.CACHED * 2
        varied = " ".join(f"token{i}" for i in range(400))

        assert len(cached) >= ADJUST_LENGTH_ABS_FLOOR
        assert _ngram_repetition_ratio(varied) == 0.0
        assert not is_adjustment_sane(cached, varied)

    def test_accepts_a_multi_paragraph_expansion_of_a_one_line_cached_answer(self):
        """A multi-turn "explain that in more detail" follow-up: history is
        non-empty so ADJUSTER_SKIP_DISTANCE never applies and adjust() runs for
        real. The elaboration is many times the length of the one-line cached
        answer, which is what was asked for, not a runaway - a ratio measured
        against a 31-character denominator says nothing."""
        cached = "The capital of France is Paris."
        expanded = (
            "Paris is the capital of France, and it has held that role almost "
            "continuously since the tenth century.\n\n"
            "The city sits on the Seine in the north of the country, and today "
            "it serves as the seat of government, the meeting place of both "
            "legislative chambers, and the official residence of the "
            "president.\n\n"
            "It is also by far the largest urban area in France, which is why "
            "so much of national administration, finance, and culture ended up "
            "concentrated there rather than spread across other regions."
        )

        assert len(expanded) > ADJUST_LENGTH_RATIO_MAX * len(cached)
        assert len(expanded) > ADJUST_LENGTH_ABS_FLOOR
        assert is_adjustment_sane(cached, expanded)

    def test_the_floor_gates_the_baseline_not_the_output(self):
        """Regression guard for the direction of the exemption. Same ratio on
        both sides of the floor: a short cached answer is exempt however large
        its rewrite, a long one is not. Fails if the floor is ever moved back
        onto len(adjusted), which exempts small rewrites and rejects exactly
        the large, correct elaborations it is meant to protect."""
        short_cached = "x" * 30
        long_cached = "y " * 150

        assert len(short_cached) < ADJUST_LENGTH_ABS_FLOOR
        assert len(long_cached) >= ADJUST_LENGTH_ABS_FLOOR
        assert is_adjustment_sane(short_cached, " ".join(f"token{i}" for i in range(100)))
        assert not is_adjustment_sane(long_cached, " ".join(f"token{i}" for i in range(600)))

    def test_rejects_empty_output(self):
        assert not is_adjustment_sane(self.CACHED, "   \n  ")

    def test_accepts_a_faithful_same_length_rewrite(self):
        reworded = (
            "With a canary deployment you ship the new version to just a small "
            "slice of traffic first, which lets you catch problems before "
            "everyone gets it."
        )
        assert is_adjustment_sane(self.CACHED, reworded)

    def test_accepts_a_condensation_of_a_long_cached_answer(self):
        """Shrinking is legitimate whenever the question asks for it, so the
        length bound is one-directional. Fails if a lower bound is ever added
        here instead of being left to ADJUSTER_MIN_TOPIC_OVERLAP."""
        assert is_adjustment_sane(self.CACHED, "Ship it to a few users first.")

    def test_accepts_the_widest_legitimate_expansion_in_this_file(self):
        """2.8x - the largest ratio of any faithful tone rewrite recorded in
        this file (the ELI5 gravity pair in TestIsTopicallyConsistent). Fails
        if the ratio threshold is ever tightened below the expansions the
        adjuster is supposed to produce."""
        cached = "Gravity is a fundamental force of attraction between objects with mass."
        eli5 = (
            "Imagine you have a ball. When you throw it up, it comes back down! "
            "That's because the Earth is really big and pulls everything toward it. "
            "That pulling is called gravity!"
        )

        assert len(eli5) / len(cached) < 3.0
        assert is_adjustment_sane(cached, eli5)

    def test_accepts_a_structured_rewrite_that_preserves_every_section(self):
        """The system prompt requires sections, bullets and numbered items to
        survive, so the guard must not read ordinary structure as repetition."""
        cached = (
            "**Core factors:**\n"
            "* Input variability: inputs arrive in different shapes.\n"
            "* Sequential processing: each stage depends on the previous one.\n"
            "* Resource constraints: excess work is queued rather than dropped.\n\n"
            "**Steps:**\n"
            "1. Receive an input and validate its shape.\n"
            "2. Transform it using a fixed rule set.\n"
            "3. Produce an output and log the transformation."
        )
        rewritten = (
            "**Core factors:**\n"
            "* Input variability: it gets inputs in all sorts of shapes.\n"
            "* Sequential processing: every stage leans on the one before it.\n"
            "* Resource constraints: extra work gets queued instead of dropped.\n\n"
            "**Steps:**\n"
            "1. It takes an input and checks its shape.\n"
            "2. It transforms that using a fixed set of rules.\n"
            "3. It emits an output and logs what it did."
        )

        assert is_adjustment_sane(cached, rewritten)

    def test_accepts_a_faithful_rewrite_of_an_already_templated_cached_answer(self):
        """The serve-time half of the same population. This one matters more
        than the generalize() side: the system prompt explicitly requires every
        numbered item of the cached answer to survive, so under a flat ceiling
        the prompt manufactures the repetition that discards its own output -
        adjust() becomes a silent no-op for this whole answer shape, after
        paying its full latency in front of a waiting user."""
        assert _ngram_repetition_ratio(TEMPLATED_LIST_ANSWER) > 0.3
        assert is_adjustment_sane(TEMPLATED_LIST_ANSWER, TEMPLATED_LIST_REWRITE)

    def test_rejects_a_loop_even_when_the_cached_answer_is_itself_templated(self):
        """Scaling the ceiling to the cached answer must not hand a repetitive
        cached answer a free pass: this loop restates one item over and over,
        stays under the length ratio, and is caught on repetition alone."""
        looped = "Person 1 served as President of the United States from 1789 to 1793. " * 30

        assert len(looped) < ADJUST_LENGTH_RATIO_MAX * len(TEMPLATED_LIST_ANSWER)
        assert not is_adjustment_sane(TEMPLATED_LIST_ANSWER, looped)


class TestAdjustRunawayGuard:
    """Wiring tests: prove adjust() itself falls back to the cached answer when
    the backend returns a runaway, not just that is_adjustment_sane() would
    reject it in isolation. Regression test for raising adjust()'s cap to
    DEFAULT_MAX_TOKENS - it fails if the guard is dropped from adjust()."""

    pytestmark = pytest.mark.no_model

    def test_falls_back_to_the_cached_answer_on_a_runaway(self):
        looped = (
            "A canary deployment rolls out a new version to a small subset of "
            "traffic first, so problems are caught before a full rollout. "
        ) * 12
        backend = _FakeBackend(looped)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert result == CANARY_ANSWER

    def test_falls_back_to_the_cached_answer_on_empty_output(self):
        backend = _FakeBackend("   ")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert result == CANARY_ANSWER

    def test_passes_through_a_sane_rewrite_unchanged(self):
        clean = (
            "With a canary deployment you push the new version to just a small "
            "slice of traffic first, so problems turn up before everyone sees them."
        )
        backend = _FakeBackend(clean)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert result == clean

    def test_serves_a_detailed_expansion_of_a_one_line_cached_answer(self):
        """End of the multi-turn path the guard must not break: a follow-up
        asking for more detail on a one-line cached answer gets the
        elaboration it asked for, not the one-line answer back."""
        cached = "The capital of France is Paris."
        expanded = (
            "Paris is the capital of France, and it has held that role almost "
            "continuously since the tenth century.\n\n"
            "The city sits on the Seine in the north of the country, and today "
            "it serves as the seat of government, the meeting place of both "
            "legislative chambers, and the official residence of the "
            "president.\n\n"
            "It is also by far the largest urban area in France, which is why "
            "so much of national administration, finance, and culture ended up "
            "concentrated there rather than spread across other regions."
        )
        backend = _FakeBackend(expanded)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.adjust("can you explain that in more detail?", cached))

        assert result == expanded
