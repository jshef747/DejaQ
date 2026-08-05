import asyncio

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
    """Deterministic tests for the post-hoc fallback, no Ollama required."""

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


class TestNoLeakingFewShot:
    """Regression guard: the photosynthesis few-shot that caused the original
    leak must never come back into the adjuster's prompt construction, in
    either adjust() or its sibling generalize()."""

    pytestmark = pytest.mark.no_model

    _LEAKING_SNIPPETS = [
        "provide a detailed analysis of photosynthesis",
        "Photosynthesis is how plants make food from sunlight",
        "biochemical process by which plants, algae, and certain bacteria",
        "Photosynthesis is the process by which plants convert light energy into chemical energy, producing glucose and oxygen from carbon dioxide and water.",
    ]

    def test_leaking_fewshot_absent_from_adjust_prompt(self):
        backend = _FakeBackend("some reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.adjust("explain that in detail", CANARY_ANSWER))

        sent = backend.requests[0]
        all_content = " ".join(m["content"] for m in sent.messages)
        for snippet in self._LEAKING_SNIPPETS:
            assert snippet not in all_content, f"leaking few-shot content resurfaced: {snippet!r}"

    def test_leaking_fewshot_absent_from_generalize_prompt(self):
        backend = _FakeBackend("some reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(CANARY_ANSWER))

        sent = backend.requests[0]
        all_content = " ".join(m["content"] for m in sent.messages)
        for snippet in self._LEAKING_SNIPPETS:
            assert snippet not in all_content, f"leaking few-shot content resurfaced: {snippet!r}"

    def test_generalize_sends_temperature_zero(self):
        backend = _FakeBackend("some reply")
        service = ContextAdjusterService(backend, "qwen_1_5b", backend, "phi_generalizer")

        asyncio.run(service.generalize(CANARY_ANSWER))

        assert backend.requests[0].temperature == 0
