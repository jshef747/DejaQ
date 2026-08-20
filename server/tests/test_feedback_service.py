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
