import asyncio
import re

import pytest

from app.config import (
    ADJUST_LENGTH_ABS_FLOOR,
    ADJUST_LENGTH_RATIO_MAX,
    ADJUST_NGRAM_REPEAT_RATIO_MAX,
    DEFAULT_MAX_TOKENS,
    GENERALIZE_LENGTH_RATIO_MAX,
    GENERALIZE_NGRAM_REPEAT_RATIO_MAX,
    OLLAMA_NUM_CTX,
    REWRITE_MAX_TOKENS,
)
from app.services.model_backends import CompletionRequest, CompletionResult
from app.services import context_adjuster
from app.services.context_adjuster import (
    ContextAdjusterService,
    _GENERALIZE_STOP,
    _language_preserved,
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
def _templated_pass(frame: str) -> str:
    return "\n".join(
        frame.format(n=i + 1, start=1789 + i * 4, end=1793 + i * 4) for i in range(50)
    )


TEMPLATED_LIST_ANSWER = _templated_pass(
    "{n}. Person {n} served as President of the United States from {start} to {end}."
)

# One pass per frame, each rewording the last - the incident's documented
# runaway shape ("rewords itself each pass, so no literal line repeats") applied
# to a templated baseline. This is the case a repetition ceiling scaled to the
# baseline let through: every pass count stays under 1.5x the baseline's own
# repetition while its length ratio (2.3x, 3.4x) stays far under the length
# arm's 10x, so neither arm fired.
_LOOP_FRAMES = (
    "{n}. Person {n} held the office of President of the United States "
    "between {start} and {end}.",
    "{n}. Person {n} occupied the office of President of the United States "
    "across {start} through {end}.",
    "{n}. Person {n} filled the role of President of the United States "
    "over {start} until {end}.",
)

TEMPLATED_LIST_REWRITE = _templated_pass(_LOOP_FRAMES[0])


def templated_self_paraphrase_loop(passes: int) -> str:
    return "\n".join(_templated_pass(frame) for frame in _LOOP_FRAMES[:passes])


# The counter-population to the templated list above: ordinary prose with no
# repetition of its own (0.000), paired with pure self-paraphrase loops around
# it that happen to land at roughly its size. Nothing here may be exempted -
# every repeated 4-gram in these outputs was invented, not inherited.
PROSE_ANSWER = (
    "A canary deployment routes a small share of production traffic to a new "
    "version while everyone else stays on the current one, so failures show up "
    "against real requests before they reach the whole user base. Teams usually "
    "start somewhere near one percent, watch error rates and latency against the "
    "unchanged baseline, and widen the slice in steps once the numbers hold. If "
    "something regresses, the rollback is a routing change rather than a "
    "redeploy, which is why the pattern is popular for services where a bad "
    "release is expensive to undo. It costs more infrastructure than a straight "
    "rollout, since both versions run at once for as long as the bake takes."
)
_PROSE_LOOP_SENTENCES = (
    "A canary deployment sends a little of the traffic to the new version. ",
    "A canary deployment routes a bit of the traffic to the newer version. ",
    "A canary deployment directs some of the traffic to the fresh version. ",
    "A canary deployment passes part of the traffic to the updated version. ",
    "A canary deployment moves a slice of the traffic to the latest version. ",
    "A canary deployment shifts a portion of the traffic to the newest version. ",
    "A canary deployment hands a fraction of the traffic to the second version. ",
    "A canary deployment gives a share of the traffic to the revised version. ",
    "A canary deployment feeds a sliver of the traffic to the current version. ",
    "A canary deployment steers a segment of the traffic to the added version. ",
)


def prose_self_paraphrase_loop(sentences: int) -> str:
    return "".join(_PROSE_LOOP_SENTENCES[:sentences])


# The population between the two above, and by far the most common answer shape
# of the three: ordinary prose carrying a few parallel bullets, repetitive
# enough to clear the ceiling (0.088) without being templated. It is what turns
# the baseline condition into a binary gate - once it opens, a same-size loop
# over it is exempted however repetitive it is, unless the output's own
# repetition is also compared against the baseline's.
MILD_STRUCTURE_ANSWER = (
    "Blue-green deployment keeps two identical production environments and cuts "
    "traffic from one to the other in a single switch, so a release becomes a "
    "routing change instead of a gradual rollout. Three properties follow from "
    "that:\n"
    "- Speed: the standby environment is already running, so a revert costs one "
    "routing change.\n"
    "- Risk: the standby environment is already verified, so a revert costs one "
    "known state.\n"
    "- Price: the standby environment is already paid for, so a revert costs one "
    "idle cluster.\n"
    "Most teams accept the duplicated infrastructure for the minutes it saves "
    "during an incident."
)
_MILD_STRUCTURE_LOOP_SENTENCES = (
    "A blue-green deployment switches all of the traffic to the new environment at once. ",
    "A blue-green deployment switches all of the traffic to the newer environment at once. ",
    "A blue-green deployment switches all of the traffic to the fresh environment at once. ",
    "A blue-green deployment switches all of the traffic to the second environment at once. ",
    "A blue-green deployment switches all of the traffic to the standby environment at once. ",
    "A blue-green deployment switches all of the traffic to the updated environment at once. ",
    "A blue-green deployment switches all of the traffic to the latest environment at once. ",
)


def mild_structure_self_paraphrase_loop(sentences: int) -> str:
    return "".join(_MILD_STRUCTURE_LOOP_SENTENCES[:sentences])


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

    def __init__(self, reply: str, done_reason: str | None = "stop"):
        self.reply = reply
        self.done_reason = done_reason
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return CompletionResult(text=self.reply, done_reason=self.done_reason)


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

    def test_falls_back_to_cached_answer_on_a_language_switch(self):
        """dejaq-acceptance-fixes report, defect #4: a Hebrew cached answer
        adjusted into English. The shared number ("180") is enough to clear
        is_topically_consistent's overlap floor, so only the dedicated
        script check catches the switch."""
        cached_hebrew = "15 כפול 12 שווה ל-180."
        translated = "15 multiplied by 12 equals 180."
        backend = _FakeBackend(translated)
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.adjust("give me the short version", cached_hebrew))

        assert result == cached_hebrew

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
        budget must cover the largest answer that can reach it - not the
        default a request runs under. A smaller cap truncates the stored
        rewrite mid-sentence, and a truncated STORED answer never self-heals:
        it is what every future cache hit serves."""
        backend = _FakeBackend("The mechanism converts an input into an output.")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(CANARY_ANSWER))

        assert backend.requests[0].max_tokens == REWRITE_MAX_TOKENS

    def test_adjust_can_reproduce_a_maximally_sized_answer(self):
        """The adjust() system prompt requires every section, bullet and named
        entity to survive, so its output budget must cover the largest stored
        answer that can reach it. A smaller cap truncates a long stored answer
        mid-sentence, and nothing downstream catches it: the backend ignores
        done_reason and the topic-overlap net passes on a truncated prefix."""
        backend = _FakeBackend("A canary deployment ships to a small slice of traffic first.")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert backend.requests[0].max_tokens == REWRITE_MAX_TOKENS

    def test_the_rewrite_budget_clears_the_largest_answer_that_can_reach_it(self):
        """DEFAULT_MAX_TOKENS is only the budget a request gets when the client
        sends no limit of its own; a client may ask for more, up to the ceiling
        those requests are clamped to. Rewriting under a budget smaller than
        that ceiling truncates the stored copy mid-sentence again, which is the
        failure this whole guard exists to prevent - so the rewrite budget must
        stay at or above it, and inside the context window that has to hold
        both this generation and the answer being rewritten."""
        assert REWRITE_MAX_TOKENS >= 8192
        assert REWRITE_MAX_TOKENS >= DEFAULT_MAX_TOKENS
        assert REWRITE_MAX_TOKENS * 2 <= OLLAMA_NUM_CTX

    def test_both_rewrite_steps_set_a_context_window(self):
        """num_ctx bounds the prompt as well as the generation, and these two
        prompts carry a whole answer on top of REWRITE_MAX_TOKENS of output -
        left at Ollama's default the pair overflows and the head of the prompt
        is dropped silently. The window has to hold both."""
        backend = _FakeBackend("short reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(CANARY_ANSWER))
        asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        for request in backend.requests:
            assert request.num_ctx == OLLAMA_NUM_CTX
            assert request.num_ctx >= request.max_tokens * 2

    def test_a_context_window_is_opt_in_per_request(self):
        """The window stays a per-request opt-in rather than a backend-wide
        default: only the roles sharing a model with a rewrite role send it
        (see test_every_role_on_a_rewrite_model_sends_the_same_window below),
        and the local answer model - gemma4:e4b, which shares with none - keeps
        Ollama's own. Fails if the window is ever moved onto the shared
        backend, which would apply it to that model too."""
        assert CompletionRequest(
            model_name="qwen_1_5b",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
            temperature=0,
        ).num_ctx is None

    def test_every_role_on_a_rewrite_model_sends_the_same_window(self):
        """Ollama treats a changed runner option as a reload of that model, so
        two windows on one model tag unload and reload it between consecutive
        roles - enrich() then adjust() on qwen2.5:1.5b run back to back on
        every multi-turn cache hit, with the user waiting. The enricher,
        normalizer and validator therefore send the rewrite roles' window even
        though their own prompts are a few hundred tokens; it costs nothing
        extra, since the model is already loaded at this window whenever
        generalize()/adjust() run."""
        from app.services.context_enricher import ContextEnricherService
        from app.services.normalizer import NormalizerService
        from app.services.validator import ValidatorService

        backend = _FakeBackend("best pizza")
        asyncio.run(ContextEnricherService(backend, "qwen_1_5b").enrich(
            "what about rome?", [{"role": "user", "content": "where should I eat?"}],
        ))
        asyncio.run(NormalizerService(backend, "gemma_e2b").normalize(
            "what is the best pizza in rome?",
        ))
        asyncio.run(ValidatorService(backend, "gemma_e2b").validate(
            "capital of france?", "what is the capital of france?", "Paris.",
        ))

        assert len(backend.requests) == 3
        for request in backend.requests:
            assert request.num_ctx == OLLAMA_NUM_CTX

    def test_a_workspace_override_actually_changes_the_request_sent(self):
        """The whole point of the per-workspace budget override (see
        llm_config_service.py) is that it changes real generation behavior,
        not just a persisted number - a fresh ContextAdjusterService built
        with an override must send that override's values to the backend,
        not the shipped globals."""
        backend = _FakeBackend("short reply")
        service = ContextAdjusterService(
            backend, "qwen_1_5b", backend, "phi_generalizer",
            rewrite_max_tokens=16000, num_ctx=65536,
        )

        asyncio.run(service.generalize(CANARY_ANSWER))
        asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        for request in backend.requests:
            assert request.max_tokens == 16000
            assert request.num_ctx == 65536
        # Confirms the override is real, not coincidentally equal to the default.
        assert 16000 != REWRITE_MAX_TOKENS
        assert 65536 != OLLAMA_NUM_CTX

    def test_both_rewrite_steps_send_the_same_budget(self):
        """One budget, not two: the same answer passes through generalize() at
        store time and adjust() at serve time, so a gap between them truncates
        on whichever side is smaller."""
        backend = _FakeBackend("short reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(CANARY_ANSWER))
        asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert backend.requests[0].max_tokens == backend.requests[1].max_tokens


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


class TestLanguagePreserved:
    pytestmark = pytest.mark.no_model

    def test_hebrew_to_hebrew_preserved(self):
        assert _language_preserved("הבירה של צרפת היא פריז.", "בירת צרפת היא פריז.")

    def test_hebrew_to_english_flagged(self):
        assert not _language_preserved("הבירה של צרפת היא פריז.", "The capital of France is Paris.")

    def test_hebrew_keeping_one_latin_abbreviation_preserved(self):
        assert _language_preserved("הסמל הכימי של זהב הוא Au.", "הסמל הכימי עבור זהב הוא Au.")

    def test_english_to_english_preserved_regardless_of_content(self):
        # Only a script CHANGE trips this - an English source has nothing to
        # "preserve" here, whatever the rewrite says.
        assert _language_preserved("The capital of France is Paris.", "Totally different content here.")

    def test_short_non_hebrew_source_is_not_penalized(self):
        # Below the non-Latin-script ratio floor - nothing to preserve.
        assert _language_preserved("Au.", "Gold's symbol is Au.")


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
        """generalize()'s max_tokens moved from 1024 to REWRITE_MAX_TOKENS
        (8x more budget) so a long, factual answer stops truncating. This
        proves that does not weaken the guard: take the real captured
        incident text (which ran to completion at the OLD 1024-token cap) and
        extend it with more passes of its own self-paraphrasing, simulating
        the same loop given the extra room the new budget allows. Both the
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

    def test_rejects_the_real_captured_garbled_hebrew_answer(self):
        """dejaq-acceptance-fixes report, defect #2: a genuine store-time
        capture. Raw Hebrew answer (Vienna is the capital of Austria)
        generalized into "Vina." - not Vienna, not Canberra, not a real
        word in either language. Neither the length nor repetition signal
        can see this (short output, no repetition); content-word overlap
        (borrowed from is_topically_consistent) is what catches it."""
        raw = "וינה היא בירת אוסטריה."
        garbled = "Vina."
        assert not is_generalization_sane(raw, garbled)

    def test_rejects_a_hebrew_answer_translated_into_english(self):
        """dejaq-acceptance-fixes report, defect #4: a live Hebrew answer
        generalized into English instead of staying Hebrew. Zero literal
        word overlap between the two scripts, so this is caught by the same
        content-preservation check as the garbled case above - and it also
        fails whenever the model changes the answer's language, not only
        when it garbles it outright."""
        raw = "הבירה של צרפת היא **פריז**."
        translated = "The capital of France is Paris."
        assert not is_generalization_sane(raw, translated)

    def test_accepts_a_faithful_hebrew_rewrite_that_keeps_the_language(self):
        raw = "הבירה של צרפת היא פריז."
        neutral = "בירת צרפת היא פריז."
        assert is_generalization_sane(raw, neutral)

    def test_rejects_an_english_mistranslation_that_leaks_a_shared_proper_noun(self):
        """dejaq-acceptance-fixes report, defect #4's measured residual gap:
        the raw Hebrew answer itself parenthetically glosses an English
        proper noun ("... הוא שקט (Pacific Ocean)"), so a FULL English
        mistranslation still shares that one token with the raw answer and
        clears is_topically_consistent's overlap floor (real sweep: 6/15
        Hebrew answers still drifted after the content-overlap guard alone).
        _language_preserved (script composition, not word overlap) is what
        catches it - is_generalization_sane must call both."""
        raw = "האוקיינוס הגדול בעולם הוא שקט (Pacific Ocean)."
        mistranslated = "The largest ocean in the world is the Pacific Ocean."
        assert not is_generalization_sane(raw, mistranslated)

    def test_rejects_an_english_mistranslation_that_leaks_a_shared_number(self):
        raw = "15 כפול 12 שווה ל-180."
        mistranslated = "15 multiplied by 12 equals 180."
        assert not is_generalization_sane(raw, mistranslated)

    def test_accepts_a_hebrew_rewrite_that_keeps_one_latin_abbreviation(self):
        """A faithful Hebrew rewrite legitimately keeps a short embedded
        Latin term (a chemical symbol, a currency sign) - that alone must
        not read as a language switch."""
        raw = "הסמל הכימי של זהב הוא Au."
        neutral = "הסמל הכימי עבור זהב הוא Au."
        assert is_generalization_sane(raw, neutral)

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
        """The other half of the same rule: exempting a same-size rewrite of a
        repetitive input must not hand every loop over that input a free pass.
        This one collapses onto a single item and restates it - shorter than
        the raw answer (0.6x), so the length arm never fires and only the
        repetition ceiling catches it, which it can because the collapse took
        the output out of the exemption band."""
        looped = "Person 1 served as President of the United States from 1789 to 1793. " * 30

        assert len(looped) < len(TEMPLATED_LIST_ANSWER)
        assert not is_generalization_sane(TEMPLATED_LIST_ANSWER, looped)

    def test_rejects_a_self_paraphrasing_loop_over_a_templated_raw_answer(self):
        """Regression guard for the fail-open band a baseline-scaled ceiling
        opened: a loop that emits the faithful rewrite and then keeps going for
        another pass or two, rewording its frame each time so nothing repeats
        literally. Its repetition sits under 1.5x the raw answer's own and its
        length (2.3x, 3.4x) under the 10x length arm, so a scaled ceiling
        served it. Against the unmodified 0.08 ceiling - which applies because
        the growth took it out of the exemption band - it is rejected
        decisively."""
        for passes in (2, 3):
            looped = templated_self_paraphrase_loop(passes)
            ratio = len(looped) / len(TEMPLATED_LIST_ANSWER)

            assert 1.3 < ratio < GENERALIZE_LENGTH_RATIO_MAX
            assert _ngram_repetition_ratio(looped) > 0.4
            assert _ngram_repetition_ratio(looped) < 1.5 * _ngram_repetition_ratio(
                TEMPLATED_LIST_ANSWER
            )
            assert not is_generalization_sane(TEMPLATED_LIST_ANSWER, looped)

    def test_rejects_a_same_size_loop_over_a_raw_answer_with_no_repetition(self):
        """The size exemption must not fire when there was no repetition to
        inherit. These loops sit INSIDE the length band (0.88x, 1.10x) and
        under the 10x length arm, so size alone would exempt them - but the raw
        answer scores 0.000, meaning every repeated 4-gram in the output was
        invented. This is the ordinary-prose population the 0.08 ceiling was
        calibrated against, and it governs here exactly as it always has."""
        assert _ngram_repetition_ratio(PROSE_ANSWER) == 0.0

        for sentences in (8, 10):
            looped = prose_self_paraphrase_loop(sentences)
            ratio = len(looped) / len(PROSE_ANSWER)

            assert 1 / 1.3 < ratio < 1.3
            assert _ngram_repetition_ratio(looped) > 0.08
            assert not is_generalization_sane(PROSE_ANSWER, looped)

    def test_rejects_a_same_size_loop_over_a_mildly_repetitive_raw_answer(self):
        """The baseline condition must be a comparison, not a binary gate. This
        raw answer is a few parallel bullets inside ordinary prose, so it clears
        the ceiling on its own (0.088) and opens the gate - after which a
        same-size loop was exempted no matter how repetitive it was. These loops
        sit inside the length band and under the 10x length arm, and invent
        every 4-gram they repeat: they are 6-7x more repetitive than the answer
        they were handed, which is the signal that rejects them."""
        baseline_repetition = _ngram_repetition_ratio(MILD_STRUCTURE_ANSWER)

        assert baseline_repetition > GENERALIZE_NGRAM_REPEAT_RATIO_MAX

        for sentences in (6, 7):
            looped = mild_structure_self_paraphrase_loop(sentences)
            ratio = len(looped) / len(MILD_STRUCTURE_ANSWER)

            assert 1 / 1.3 < ratio < 1.3
            assert len(looped) < GENERALIZE_LENGTH_RATIO_MAX * len(MILD_STRUCTURE_ANSWER)
            assert (
                _ngram_repetition_ratio(looped) - baseline_repetition
                > GENERALIZE_NGRAM_REPEAT_RATIO_MAX
            )
            assert not is_generalization_sane(MILD_STRUCTURE_ANSWER, looped)


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

    def test_refuses_to_store_a_truncated_rewrite(self):
        """A truncated rewrite is SHORTER than the raw answer with no
        elevated repetition - exactly the profile is_generalization_sane()
        accepts as clean, so this is the one failure mode that check cannot
        catch. done_reason is the only signal that can: this must fall back
        to the complete raw answer even though the truncated text itself
        would sail through every other guard. This is the failure that
        matters most in this file - whatever generalize() returns here is
        what gets PERSISTED to ChromaDB, so a truncated copy never
        self-heals; every future cache hit would serve the same cut-off
        text forever."""
        raw = "The mechanism has three independent stages: validate, transform, and emit."
        truncated = "The mechanism has three independent stages: validate, trans"
        backend = _FakeBackend(truncated, done_reason="length")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.generalize(raw))

        assert result == raw

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

    def test_content_containing_the_stop_marker_round_trips_untruncated(self):
        """B14 regression: a rewrite that faithfully reproduces an answer
        containing a legitimate '*****' markdown thematic break used to be
        silently cut at the marker (done_reason='stop' looks identical to a
        real runaway trip, and the truncated prefix passes
        is_generalization_sane cleanly). generalize() must now detect the
        stop-hit and retry once without the stop sequence, returning the
        full untruncated text."""
        raw = "Section one covers setup.\n\n\n*****\n\nSection two covers teardown."

        class _StopThenFullBackend:
            def __init__(self):
                self.calls = 0

            async def complete(self, request):
                self.calls += 1
                if request.stop:
                    # Simulates Ollama truncating at the stop marker: only the
                    # text before it comes back, with done_reason="stop".
                    return CompletionResult(text="Section one covers setup.", done_reason="stop")
                return CompletionResult(text=raw, done_reason="stop")

        backend = _StopThenFullBackend()
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.generalize(raw))

        assert result == raw
        assert backend.calls == 2


class TestIsAdjustmentSane:
    """Pure unit tests for the adjust() serve-time safety net, the sibling of
    is_generalization_sane() above. adjust() carries no stop string (its
    few-shots are chat turns, with no separator marker to stop on) and runs at
    REWRITE_MAX_TOKENS on the synchronous cache-hit path, so this guard is the
    only bound on a runaway rewrite reaching a waiting user (ADJUST_TIMEOUT_
    SECONDS bounds how long it can take to get there, not what it returns)."""

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
        """The exemption must not hand every loop over a repetitive cached
        answer a free pass: this one collapses onto a single item and restates
        it, stays under the length ratio, and is caught on repetition alone -
        the collapse itself is what takes it out of the exemption band."""
        looped = "Person 1 served as President of the United States from 1789 to 1793. " * 30

        assert len(looped) < ADJUST_LENGTH_RATIO_MAX * len(TEMPLATED_LIST_ANSWER)
        assert not is_adjustment_sane(TEMPLATED_LIST_ANSWER, looped)

    def test_rejects_a_self_paraphrasing_loop_over_a_templated_cached_answer(self):
        """The serve-time half of the same regression guard: a loop that
        reworded its frame each pass evaded a baseline-scaled ceiling while
        staying under the 10x length arm. The unmodified 0.08 ceiling applies
        here because the growth left the exemption band."""
        for passes in (2, 3):
            looped = templated_self_paraphrase_loop(passes)
            ratio = len(looped) / len(TEMPLATED_LIST_ANSWER)

            assert 1.3 < ratio < ADJUST_LENGTH_RATIO_MAX
            assert _ngram_repetition_ratio(looped) > 0.4
            assert _ngram_repetition_ratio(looped) < 1.5 * _ngram_repetition_ratio(
                TEMPLATED_LIST_ANSWER
            )
            assert not is_adjustment_sane(TEMPLATED_LIST_ANSWER, looped)

    def test_rejects_a_same_size_loop_over_a_cached_answer_with_no_repetition(self):
        """The serve-time half: a loop landing at the cached answer's own size
        over a cached answer that had no repetition of its own. is_topically_
        consistent() is blind to it - every repeated phrase is drawn from the
        cached answer's vocabulary, so it scores near the maximum - which
        leaves the repetition ceiling as the only thing that sees it, and the
        size exemption must not disarm it here."""
        assert _ngram_repetition_ratio(PROSE_ANSWER) == 0.0

        for sentences in (8, 10):
            looped = prose_self_paraphrase_loop(sentences)
            ratio = len(looped) / len(PROSE_ANSWER)

            assert 1 / 1.3 < ratio < 1.3
            assert is_topically_consistent(looped, PROSE_ANSWER)
            assert not is_adjustment_sane(PROSE_ANSWER, looped)

    def test_rejects_a_same_size_loop_over_a_mildly_repetitive_cached_answer(self):
        """The serve-time half: a cached answer repetitive enough to open the
        baseline gate (0.088, a few parallel bullets inside prose) must not hand
        every same-size loop over it a free pass. The loop stays inside the
        length band and under the 10x length arm, and is caught only because its
        own repetition runs far past what the cached answer could have supplied."""
        baseline_repetition = _ngram_repetition_ratio(MILD_STRUCTURE_ANSWER)

        assert baseline_repetition > ADJUST_NGRAM_REPEAT_RATIO_MAX
        assert len(MILD_STRUCTURE_ANSWER) >= ADJUST_LENGTH_ABS_FLOOR

        for sentences in (6, 7):
            looped = mild_structure_self_paraphrase_loop(sentences)
            ratio = len(looped) / len(MILD_STRUCTURE_ANSWER)

            assert 1 / 1.3 < ratio < 1.3
            assert ratio < ADJUST_LENGTH_RATIO_MAX
            assert (
                _ngram_repetition_ratio(looped) - baseline_repetition
                > ADJUST_NGRAM_REPEAT_RATIO_MAX
            )
            assert not is_adjustment_sane(MILD_STRUCTURE_ANSWER, looped)


class TestAdjustRunawayGuard:
    """Wiring tests: prove adjust() itself falls back to the cached answer when
    the backend returns a runaway, not just that is_adjustment_sane() would
    reject it in isolation. Regression test for raising adjust()'s cap to
    REWRITE_MAX_TOKENS - it fails if the guard is dropped from adjust()."""

    pytestmark = pytest.mark.no_model

    def test_falls_back_to_the_cached_answer_when_the_rewrite_stalls(self, monkeypatch):
        """The one guard that does not need the generation to come back first:
        every other check here is post-hoc, so none of them bounds how long a
        waiting user holds the cache-hit path open."""

        class _StallingBackend:
            async def complete(self, request):
                await asyncio.sleep(60)
                raise AssertionError("the deadline should have fired first")

        monkeypatch.setattr(context_adjuster, "ADJUST_TIMEOUT_SECONDS", 0.01)
        backend = _StallingBackend()
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        result = asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        assert result == CANARY_ANSWER

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
