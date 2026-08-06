import asyncio
import re

import pytest

from app.services.context_adjuster import ContextAdjusterService, is_topically_consistent

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


class TestGeneralize:
    pytestmark = pytest.mark.phi

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
    the two populations measured in the safety-net threshold sweep (report:
    dejaq-safetynet-necessity): on-topic rewrites that legitimately condense a
    long cached answer down to a handful of shared nouns must be ACCEPTED,
    drifted output that survives on one coincidental word or none must still be
    REJECTED.

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
