import asyncio

import pytest

pytestmark = pytest.mark.no_model


class FakeMemory:
    def __init__(self):
        self.negative_count = 0
        self.score = 0.0
        self.deleted: list[str] = []
        self.missing = False
        # Simulates the background store not having written the entry yet:
        # the first `fail_count` attempts raise KeyError, then it "arrives".
        self.fail_count = 0

    def _maybe_race(self, doc_id: str) -> None:
        if self.missing:
            raise KeyError(doc_id)
        if self.fail_count > 0:
            self.fail_count -= 1
            raise KeyError(doc_id)

    def get_negative_count(self, doc_id: str) -> int:
        self._maybe_race(doc_id)
        return self.negative_count

    def delete_entry(self, doc_id: str) -> bool:
        if self.missing:
            raise KeyError(doc_id)
        self.deleted.append(doc_id)
        return True

    def update_score(self, doc_id: str, delta: float) -> float:
        self._maybe_race(doc_id)
        self.score += delta
        if delta < 0:
            self.negative_count += 1
        return self.score


def _fake_sleep(calls: list[float]):
    async def _sleep(seconds: float) -> None:
        calls.append(seconds)

    return _sleep


def test_feedback_service_positive_updates_score_and_logs(monkeypatch):
    from app.services import feedback_service

    memory = FakeMemory()
    log_calls = []

    async def _log_feedback(*args):
        log_calls.append(args)

    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)

    result = asyncio.run(
        feedback_service.submit_feedback(
            response_id="acme__eng:doc1",
            rating="positive",
            comment="good",
            workspace="acme",
            department="eng",
            validate_namespace=True,
        )
    )

    assert result.status == "ok"
    assert result.new_score == 1.0
    assert log_calls == [("acme__eng:doc1", "acme", "eng", "positive", "good")]


def test_feedback_service_first_negative_deletes(monkeypatch):
    from app.services import feedback_service

    memory = FakeMemory()

    async def _log_feedback(*args):
        return None

    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)

    result = asyncio.run(
        feedback_service.submit_feedback(
            response_id="acme__eng:doc1",
            rating="negative",
            comment=None,
            workspace="acme",
            department="eng",
            validate_namespace=True,
        )
    )

    assert result.status == "deleted"
    assert result.new_score is None
    assert memory.deleted == ["doc1"]


def test_feedback_service_missing_entry_raises(monkeypatch):
    from app.services import feedback_service

    memory = FakeMemory()
    memory.missing = True

    async def _log_feedback(*args):
        return None

    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service.asyncio, "sleep", _fake_sleep([]))

    with pytest.raises(feedback_service.FeedbackNotFound):
        asyncio.run(
            feedback_service.submit_feedback(
                response_id="acme__eng:doc1",
                rating="positive",
                comment=None,
                workspace="acme",
                department="eng",
                validate_namespace=True,
            )
        )


def test_feedback_service_namespace_mismatch_raises():
    from app.services import feedback_service

    with pytest.raises(feedback_service.FeedbackNamespaceMismatch):
        asyncio.run(
            feedback_service.submit_feedback(
                response_id="other__eng:doc1",
                rating="positive",
                comment=None,
                workspace="acme",
                department="eng",
                validate_namespace=True,
            )
        )


def test_interaction_feedback_without_messages_does_not_escalate(monkeypatch):
    from app.services import feedback_service
    from app.services.response_registry import ResponseInteraction

    interaction = ResponseInteraction(
        interaction_id="int_local",
        workspace_id=7,
        workspace_slug="acme",
        department="eng",
        cache_namespace="acme__eng",
        served_tier="local",
        response_id=None,
        message_hash="expected",
        created_at="2026-01-01T00:00:00+00:00",
        escalation_attempted=False,
        escalation_attempted_at=None,
    )

    class Registry:
        async def validate_owner(self, *args, **kwargs):
            return interaction

    async def _log_feedback(*args, **kwargs):
        return None

    async def _fail_escalate(*args, **kwargs):
        raise AssertionError("escalation should not be called")

    monkeypatch.setattr(feedback_service, "response_registry", Registry())
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service, "escalate", _fail_escalate, raising=False)

    result = asyncio.run(
        feedback_service.submit_feedback(
            response_id=None,
            interaction_id="int_local",
            rating="negative",
            comment=None,
            workspace="acme",
            workspace_id=7,
            department="eng",
            validate_namespace=True,
        )
    )

    assert result.status == "ok"
    assert result.escalation_status == "not_requested"
    assert result.escalated_response is None


def test_interaction_feedback_message_mismatch_does_not_escalate(monkeypatch):
    from app.services import feedback_service
    from app.services.response_registry import ResponseInteraction

    interaction = ResponseInteraction(
        interaction_id="int_local",
        workspace_id=7,
        workspace_slug="acme",
        department="eng",
        cache_namespace="acme__eng",
        served_tier="local",
        response_id=None,
        message_hash="not-the-submitted-hash",
        created_at="2026-01-01T00:00:00+00:00",
        escalation_attempted=False,
        escalation_attempted_at=None,
    )

    class Registry:
        async def validate_owner(self, *args, **kwargs):
            return interaction

    async def _log_feedback(*args, **kwargs):
        return None

    async def _fail_escalate(*args, **kwargs):
        raise AssertionError("escalation should not be called")

    monkeypatch.setattr(feedback_service, "response_registry", Registry())
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service, "escalate", _fail_escalate, raising=False)

    result = asyncio.run(
        feedback_service.submit_feedback(
            response_id=None,
            interaction_id="int_local",
            messages=[{"role": "user", "content": "Hello"}],
            rating="negative",
            comment=None,
            workspace="acme",
            workspace_id=7,
            department="eng",
            validate_namespace=True,
        )
    )

    assert result.status == "ok"
    assert result.escalation_status == "message_mismatch"


def test_interaction_feedback_duplicate_guard_skips_escalation(monkeypatch):
    from app.services import feedback_service
    from app.services.response_registry import ResponseInteraction, compute_messages_hash

    messages = [{"role": "user", "content": "Hello"}]
    interaction = ResponseInteraction(
        interaction_id="int_local",
        workspace_id=7,
        workspace_slug="acme",
        department="eng",
        cache_namespace="acme__eng",
        served_tier="local",
        response_id=None,
        message_hash=compute_messages_hash(messages),
        created_at="2026-01-01T00:00:00+00:00",
        escalation_attempted=True,
        escalation_attempted_at="2026-01-01T00:00:01+00:00",
    )

    class Registry:
        async def validate_owner(self, *args, **kwargs):
            return interaction

        async def acquire_escalation(self, interaction_id):
            return False

    async def _log_feedback(*args, **kwargs):
        return None

    async def _fail_escalate(*args, **kwargs):
        raise AssertionError("escalation should not be called")

    monkeypatch.setattr(feedback_service, "response_registry", Registry())
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service, "escalate", _fail_escalate, raising=False)

    result = asyncio.run(
        feedback_service.submit_feedback(
            response_id=None,
            interaction_id="int_local",
            messages=messages,
            rating="negative",
            comment=None,
            workspace="acme",
            workspace_id=7,
            department="eng",
            validate_namespace=True,
        )
    )

    assert result.status == "ok"
    assert result.escalation_status == "already_escalated"


def test_interaction_feedback_invalid_messages_raise_before_escalation(monkeypatch):
    from app.services import feedback_service
    from app.services.response_registry import ResponseInteraction

    interaction = ResponseInteraction(
        interaction_id="int_local",
        workspace_id=7,
        workspace_slug="acme",
        department="eng",
        cache_namespace="acme__eng",
        served_tier="local",
        response_id=None,
        message_hash="irrelevant",
        created_at="2026-01-01T00:00:00+00:00",
        escalation_attempted=False,
        escalation_attempted_at=None,
    )

    class Registry:
        async def validate_owner(self, *args, **kwargs):
            return interaction

    async def _log_feedback(*args, **kwargs):
        return None

    async def _fail_escalate(*args, **kwargs):
        raise AssertionError("escalation should not be called")

    monkeypatch.setattr(feedback_service, "response_registry", Registry())
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service, "escalate", _fail_escalate, raising=False)

    with pytest.raises(ValueError):
        asyncio.run(
            feedback_service.submit_feedback(
                response_id=None,
                interaction_id="int_local",
                messages=[{"role": "developer", "content": "Hello"}],
                rating="negative",
                comment=None,
                workspace="acme",
                workspace_id=7,
                department="eng",
                validate_namespace=True,
            )
        )


def test_interaction_feedback_wrong_owner_raises_not_found(monkeypatch):
    from app.services import feedback_service

    class Registry:
        async def validate_owner(self, *args, **kwargs):
            return None

    monkeypatch.setattr(feedback_service, "response_registry", Registry())

    with pytest.raises(feedback_service.FeedbackNotFound):
        asyncio.run(
            feedback_service.submit_feedback(
                response_id=None,
                interaction_id="int_other",
                messages=[{"role": "user", "content": "Hello"}],
                rating="negative",
                comment=None,
                workspace="acme",
                workspace_id=7,
                department="eng",
                validate_namespace=True,
            )
        )


# --- Store-write race: cache entry not yet written by the background task ---


def test_feedback_race_positive_retries_then_succeeds(monkeypatch):
    """Captain's exact scenario: thumbs-up lands before the store task finishes."""
    from app.services import feedback_service

    memory = FakeMemory()
    memory.fail_count = 2  # first two lookups race the store; third finds it
    sleep_calls: list[float] = []
    log_calls = []

    async def _log_feedback(*args):
        log_calls.append(args)

    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service.asyncio, "sleep", _fake_sleep(sleep_calls))

    result = asyncio.run(
        feedback_service.submit_feedback(
            response_id="acme__eng:doc1",
            rating="positive",
            comment="good",
            workspace="acme",
            department="eng",
            validate_namespace=True,
        )
    )

    assert result.status == "ok"
    assert result.new_score == 1.0
    assert sleep_calls == [0.2, 0.5]
    assert log_calls == [("acme__eng:doc1", "acme", "eng", "positive", "good")]


def test_feedback_race_negative_retries_records_row_and_escalates(monkeypatch):
    """A mistimed thumbs-down must still record feedback_log and run escalation."""
    from app.services import feedback_service
    from app.services.escalation import EscalationResult
    from app.services.response_registry import ResponseInteraction, compute_messages_hash

    messages = [{"role": "user", "content": "Hello"}]
    interaction = ResponseInteraction(
        interaction_id="int_local",
        workspace_id=7,
        workspace_slug="acme",
        department="eng",
        cache_namespace="acme__eng",
        served_tier="local",
        response_id="acme__eng:doc1",
        message_hash=compute_messages_hash(messages),
        created_at="2026-01-01T00:00:00+00:00",
        escalation_attempted=False,
        escalation_attempted_at=None,
    )

    memory = FakeMemory()
    memory.fail_count = 2

    class Registry:
        async def validate_owner(self, *args, **kwargs):
            return interaction

        async def acquire_escalation(self, interaction_id):
            return True

    sleep_calls: list[float] = []
    log_calls = []
    escalate_calls = []

    async def _log_feedback(*args, **kwargs):
        log_calls.append((args, kwargs))

    async def _fake_escalate(*, interaction, messages):
        escalate_calls.append((interaction, messages))
        return EscalationResult(escalation_status="answered")

    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(feedback_service, "response_registry", Registry())
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service, "escalate", _fake_escalate)
    monkeypatch.setattr(feedback_service.asyncio, "sleep", _fake_sleep(sleep_calls))

    result = asyncio.run(
        feedback_service.submit_feedback(
            response_id=None,
            interaction_id="int_local",
            messages=messages,
            rating="negative",
            comment=None,
            workspace="acme",
            workspace_id=7,
            department="eng",
            validate_namespace=True,
        )
    )

    assert result.status == "deleted"  # first negative on this entry: delete-on-first-negative
    assert memory.deleted == ["doc1"]
    assert sleep_calls == [0.2, 0.5]
    assert len(log_calls) == 1  # feedback_log row was written despite the race
    assert result.escalation_status == "answered"
    assert len(escalate_calls) == 1  # escalation ran despite the race


def test_feedback_unknown_id_still_fails_after_retry_budget(monkeypatch):
    """A genuinely bad response_id pays the retry delay and then correctly 404s."""
    from app.services import feedback_service

    memory = FakeMemory()
    memory.missing = True
    sleep_calls: list[float] = []

    async def _log_feedback(*args):
        return None

    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service.asyncio, "sleep", _fake_sleep(sleep_calls))

    with pytest.raises(feedback_service.FeedbackNotFound):
        asyncio.run(
            feedback_service.submit_feedback(
                response_id="acme__eng:doc-does-not-exist",
                rating="positive",
                comment=None,
                workspace="acme",
                department="eng",
                validate_namespace=True,
            )
        )

    # Full retry budget spent (3 attempts, 2 waits) before giving up.
    assert sleep_calls == [0.2, 0.5, 1.0]


def test_feedback_no_race_pays_no_retry_delay(monkeypatch):
    """Ordinary feedback, submitted after the store has completed, is not slowed down."""
    from app.services import feedback_service

    memory = FakeMemory()  # entry already present, no fail_count
    sleep_calls: list[float] = []

    async def _log_feedback(*args):
        return None

    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service.asyncio, "sleep", _fake_sleep(sleep_calls))

    result = asyncio.run(
        feedback_service.submit_feedback(
            response_id="acme__eng:doc1",
            rating="positive",
            comment=None,
            workspace="acme",
            department="eng",
            validate_namespace=True,
        )
    )

    assert result.status == "ok"
    assert sleep_calls == []


# --- Alternative drafts: keeping one of two tied cache entries --------------

def _draft_interaction(response_id="acme__eng:doc-a"):
    from app.services.response_registry import ResponseInteraction

    return ResponseInteraction(
        interaction_id="int_drafts",
        workspace_id=7,
        workspace_slug="acme",
        department="eng",
        cache_namespace="acme__eng",
        served_tier="cache",
        response_id=response_id,
        message_hash="expected",
        created_at="2026-01-01T00:00:00+00:00",
        escalation_attempted=False,
        escalation_attempted_at=None,
    )


def _patch_for_draft_choice(monkeypatch, memory, interaction=None):
    from app.services import feedback_service

    interaction = interaction or _draft_interaction()

    class Registry:
        def __init__(self):
            self.repointed: list[tuple[str, str]] = []

        async def validate_owner(self, *args, **kwargs):
            return interaction

        async def set_response_id(self, interaction_id, response_id):
            self.repointed.append((interaction_id, response_id))

    async def _log_feedback(*args, **kwargs):
        return None

    registry = Registry()
    monkeypatch.setattr(feedback_service, "response_registry", registry)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)
    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    # The pair these tests describe: doc-a was served (the interaction points at
    # it), doc-b was the alternate. Re-derivation itself is a Chroma round-trip
    # and is covered directly by TestDraftPairReDerivation below.
    monkeypatch.setattr(
        feedback_service,
        "_draft_pair_for",
        lambda served, workspace: ("acme__eng:doc-a", "acme__eng:doc-b"),
    )
    feedback_service._test_registry = registry
    return feedback_service


def _submit_draft_choice(feedback_service, **overrides):
    kwargs = dict(
        response_id=None,
        interaction_id="int_drafts",
        rating="positive",
        comment=None,
        workspace="acme",
        workspace_id=7,
        department="eng",
        validate_namespace=True,
        cache_namespace="acme__eng",
        chosen_draft_response_id="acme__eng:doc-b",
        rejected_draft_response_ids=["acme__eng:doc-a"],
    )
    kwargs.update(overrides)
    return asyncio.run(feedback_service.submit_feedback(**kwargs))


class _ScoringMemory(FakeMemory):
    """Records which entry each score change landed on."""

    def __init__(self):
        super().__init__()
        self.scored: list[tuple[str, float]] = []

    def update_score(self, doc_id: str, delta: float) -> float:
        self.scored.append((doc_id, delta))
        return super().update_score(doc_id, delta)


def test_draft_choice_scores_the_kept_entry_not_the_served_one(monkeypatch):
    """The interaction names the entry that was SERVED (draft A). A user who
    kept draft B must put the point on B."""
    memory = _ScoringMemory()
    feedback_service = _patch_for_draft_choice(monkeypatch, memory)

    result = _submit_draft_choice(feedback_service)

    assert result.status == "ok"
    assert result.draft_choice == "recorded"
    assert memory.scored == [("doc-b", 1.0)]


def test_draft_choice_leaves_the_rejected_entry_untouched(monkeypatch):
    """By the tie-breaker's own definition the loser was a high-quality match
    that another user may well prefer - it is recorded, never penalised."""
    memory = _ScoringMemory()
    feedback_service = _patch_for_draft_choice(monkeypatch, memory)

    _submit_draft_choice(feedback_service)

    assert [doc_id for doc_id, _ in memory.scored] == ["doc-b"]
    assert memory.deleted == []


def test_draft_choice_returns_the_entry_the_point_landed_on(monkeypatch):
    """So the client adopts it for any later feedback or edit - the same
    contract Edit & Save set."""
    feedback_service = _patch_for_draft_choice(monkeypatch, _ScoringMemory())

    result = _submit_draft_choice(feedback_service)

    assert result.response_id == "acme__eng:doc-b"


def test_draft_choice_rejects_a_chosen_id_from_another_namespace(monkeypatch):
    """Every draft id is client-supplied and names a ChromaDB collection."""
    from app.services.feedback_service import FeedbackNamespaceMismatch

    feedback_service = _patch_for_draft_choice(monkeypatch, _ScoringMemory())

    with pytest.raises(FeedbackNamespaceMismatch):
        _submit_draft_choice(feedback_service, chosen_draft_response_id="other__ns:doc-b")


def test_draft_choice_rejects_a_rejected_id_from_another_namespace(monkeypatch):
    """Checked even though nothing scores them - they still reach the log."""
    from app.services.feedback_service import FeedbackNamespaceMismatch

    feedback_service = _patch_for_draft_choice(monkeypatch, _ScoringMemory())

    with pytest.raises(FeedbackNamespaceMismatch):
        _submit_draft_choice(feedback_service, rejected_draft_response_ids=["other__ns:doc-a"])


def test_draft_choice_on_a_vanished_entry_is_reported_not_raised(monkeypatch):
    """Evicted, or deleted by somebody else's thumbs-down. The pick is lost;
    the answer the user kept is already on their screen, so 404 would be a lie."""
    memory = _ScoringMemory()
    memory.missing = True
    feedback_service = _patch_for_draft_choice(monkeypatch, memory)

    result = _submit_draft_choice(feedback_service)

    assert result.status == "ok"
    assert result.draft_choice == "not_found"


def test_draft_choice_requires_a_positive_rating(monkeypatch):
    """Re-checked in the service: the admin surface's schema does not enforce
    what FeedbackRequest does."""
    feedback_service = _patch_for_draft_choice(monkeypatch, _ScoringMemory())

    with pytest.raises(ValueError):
        _submit_draft_choice(feedback_service, rating="negative")


def test_feedback_without_a_draft_choice_reports_none(monkeypatch):
    """The control: an ordinary thumbs-up must not grow the field."""
    memory = _ScoringMemory()
    feedback_service = _patch_for_draft_choice(monkeypatch, memory)

    result = _submit_draft_choice(
        feedback_service,
        chosen_draft_response_id=None,
        rejected_draft_response_ids=None,
    )

    assert result.draft_choice is None
    assert memory.scored == [("doc-a", 1.0)]


def test_draft_choice_repoints_the_interaction_at_the_kept_entry(monkeypatch):
    """The part a client cannot fix for us.

    The interaction record names the draft that was SERVED, and every later
    call that sends only an interaction_id resolves through it. Left pointing
    at the discarded draft, a thumbs-down on the answer the user kept would
    delete the OTHER entry - immediately, on a first negative.
    """
    feedback_service = _patch_for_draft_choice(monkeypatch, _ScoringMemory())

    _submit_draft_choice(feedback_service)

    assert feedback_service._test_registry.repointed == [
        ("int_drafts", "acme__eng:doc-b")
    ]


def test_a_lost_draft_choice_never_repoints_the_interaction(monkeypatch):
    """The entry vanished, so the pick did not land - re-pointing at it would
    leave the interaction naming nothing at all."""
    memory = _ScoringMemory()
    memory.missing = True
    feedback_service = _patch_for_draft_choice(monkeypatch, memory)

    result = _submit_draft_choice(feedback_service)

    assert result.draft_choice == "not_found"
    assert feedback_service._test_registry.repointed == []


def test_ordinary_feedback_never_repoints_the_interaction(monkeypatch):
    feedback_service = _patch_for_draft_choice(monkeypatch, _ScoringMemory())

    _submit_draft_choice(
        feedback_service,
        chosen_draft_response_id=None,
        rejected_draft_response_ids=None,
    )

    assert feedback_service._test_registry.repointed == []


# --- Alternative drafts: the chosen id must be one of the two offered --------

def test_draft_choice_rejects_an_entry_that_was_never_offered(monkeypatch):
    """The PR 70 review's exact case.

    An unrelated entry in the caller's OWN namespace passes the namespace
    check, and before this rule it took the +1.0 and the interaction was
    re-pointed at it - so a later thumbs-down on that turn would delete an
    entry the user was never shown. The offered pair is not stored anywhere
    (no column, no second migration), so the id is re-derived instead: it must
    be the served entry or the alternate the same lookup produces for it.
    """
    memory = _ScoringMemory()
    feedback_service = _patch_for_draft_choice(monkeypatch, memory)

    with pytest.raises(ValueError) as exc:
        _submit_draft_choice(
            feedback_service, chosen_draft_response_id="acme__eng:unrelated"
        )

    # An honest reason, not a silent ignore.
    assert "not one of the drafts offered" in str(exc.value)
    assert memory.scored == []
    assert feedback_service._test_registry.repointed == []


def test_draft_choice_still_accepts_the_alternate(monkeypatch):
    """The legitimate pick - draft B - is unaffected by the rule above."""
    memory = _ScoringMemory()
    feedback_service = _patch_for_draft_choice(monkeypatch, memory)

    result = _submit_draft_choice(feedback_service)

    assert result.draft_choice == "recorded"
    assert memory.scored == [("doc-b", 1.0)]


def test_draft_choice_still_accepts_keeping_the_served_answer(monkeypatch):
    """Draft A is the answer that was served, so keeping it needs no lookup at
    all - and a user who agrees with what they were given is the common pick."""
    memory = _ScoringMemory()
    feedback_service = _patch_for_draft_choice(monkeypatch, memory)
    # Prove the served-id case does not depend on re-derivation working.
    monkeypatch.setattr(
        feedback_service,
        "_draft_pair_for",
        lambda served, workspace: pytest.fail("served id must not need a lookup"),
    )

    result = _submit_draft_choice(
        feedback_service,
        chosen_draft_response_id="acme__eng:doc-a",
        rejected_draft_response_ids=["acme__eng:doc-b"],
    )

    assert result.draft_choice == "recorded"
    assert memory.scored == [("doc-a", 1.0)]


class _PoolMemory:
    """Enough of MemoryService for _draft_pair_for: the entry's stored query
    (which IS the cache key) and the ranked candidate pool it looks up."""

    def __init__(self, query, candidates):
        self._query = query
        self._candidates = candidates

    def get_entry_query(self, entry_id):
        return self._query

    def lookup_cache_pool(self, normalized_query):
        return (self._candidates, None, None)


def _pool_candidate(entry_id, distance, answer, score=0.0):
    from app.services.memory_chromaDB import CacheLookupResult

    return CacheLookupResult(
        hit=True,
        generalized_answer=answer,
        entry_id=entry_id,
        distance=distance,
        matched_query="how do i reset the password",
        score=score,
    )


class TestDraftPairReDerivation:
    """`_draft_pair_for` - the lookup that stands in for the ids nobody stored."""

    def _service(self, monkeypatch, memory):
        from app.services import feedback_service

        monkeypatch.setattr(feedback_service, "get_memory_service", lambda ns: memory)
        # Not a configured workspace here; the shipped CACHE_DRAFTS_* defaults
        # are the fallback, which is exactly what an un-overridden workspace uses.
        return feedback_service

    def test_re_derives_the_pair_that_was_offered(self, monkeypatch):
        memory = _PoolMemory(
            "how do i reset the password",
            [
                _pool_candidate("doc-a", 0.0089, "Call the service desk on extension 4400."),
                _pool_candidate("doc-b", 0.0184, "Email support and they will send a reset link."),
            ],
        )
        feedback_service = self._service(monkeypatch, memory)

        assert feedback_service._draft_pair_for("acme__eng:doc-a", "acme") == (
            "acme__eng:doc-a",
            "acme__eng:doc-b",
        )

    def test_an_unrelated_entry_is_not_in_the_pair(self, monkeypatch):
        memory = _PoolMemory(
            "how do i reset the password",
            [
                _pool_candidate("doc-a", 0.0089, "Call the service desk on extension 4400."),
                _pool_candidate("doc-b", 0.0184, "Email support and they will send a reset link."),
            ],
        )
        feedback_service = self._service(monkeypatch, memory)

        pair = feedback_service._draft_pair_for("acme__eng:doc-a", "acme")

        assert "acme__eng:unrelated" not in pair

    def test_a_vanished_entry_pairs_with_nothing(self, monkeypatch):
        feedback_service = self._service(monkeypatch, _PoolMemory(None, []))

        assert feedback_service._draft_pair_for("acme__eng:doc-a", "acme") is None

    def test_an_untied_pool_pairs_with_nothing(self, monkeypatch):
        """No tie means no drafts were offered, so no chosen id is derivable."""
        memory = _PoolMemory(
            "how do i reset the password",
            [_pool_candidate("doc-a", 0.0089, "Call the service desk on extension 4400.")],
        )
        feedback_service = self._service(monkeypatch, memory)

        assert feedback_service._draft_pair_for("acme__eng:doc-a", "acme") is None
