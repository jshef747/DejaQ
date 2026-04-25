import asyncio

import pytest


class FakeMemory:
    def __init__(self):
        self.negative_count = 0
        self.score = 0.0
        self.deleted: list[str] = []
        self.missing = False

    def get_negative_count(self, doc_id: str) -> int:
        if self.missing:
            raise KeyError(doc_id)
        return self.negative_count

    def delete_entry(self, doc_id: str) -> bool:
        if self.missing:
            raise KeyError(doc_id)
        self.deleted.append(doc_id)
        return True

    def update_score(self, doc_id: str, delta: float) -> float:
        if self.missing:
            raise KeyError(doc_id)
        self.score += delta
        if delta < 0:
            self.negative_count += 1
        return self.score


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
            org="acme",
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
            org="acme",
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

    with pytest.raises(feedback_service.FeedbackNotFound):
        asyncio.run(
            feedback_service.submit_feedback(
                response_id="acme__eng:doc1",
                rating="positive",
                comment=None,
                org="acme",
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
                org="acme",
                department="eng",
                validate_namespace=True,
            )
        )
