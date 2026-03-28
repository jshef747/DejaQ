import pytest
from unittest.mock import MagicMock, patch

from app.services.feedback_service import FeedbackService
from app.services.memory_chromaDB import MemoryService

pytestmark = pytest.mark.no_model


def _make_service(tmp_path):
    """Build a FeedbackService with a real MemoryService (tmp ChromaDB) and a mocked Redis."""
    memory = MemoryService(
        collection_name="feedback_test",
        persist_directory=str(tmp_path / "chroma"),
    )
    svc = FeedbackService.__new__(FeedbackService)
    svc._memory = memory
    svc._redis = MagicMock()
    svc._redis.ping.return_value = True
    return svc, memory


class TestScoreMechanics:
    def test_positive_increments_score(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("test query", "test answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]

        result = svc.submit_feedback(entry_id, "positive")

        assert result.feedback_score == 1
        assert result.status == "ok"
        assert result.deleted is False

    def test_negative_decrements_score(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("test query", "test answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]

        result = svc.submit_feedback(entry_id, "negative")

        assert result.feedback_score == -1
        assert result.status == "ok"

    def test_score_starts_at_zero(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("fresh query", "fresh answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]

        meta = memory.get_entry_metadata(entry_id)
        assert int(meta.get("feedback_score", 0)) == 0

    def test_multiple_ratings_accumulate(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("multi query", "multi answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]

        svc.submit_feedback(entry_id, "positive")
        svc.submit_feedback(entry_id, "positive")
        result = svc.submit_feedback(entry_id, "negative")

        assert result.feedback_score == 1

    def test_not_found_returns_status(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        result = svc.submit_feedback("nonexistent-id", "positive")
        assert result.status == "not_found"
        assert result.feedback_score == 0


class TestFlagging:
    def test_score_at_flag_threshold_deletes_entry(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("flag query", "flag answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]
        # Manually set score to -2 so next negative hits -3 (FLAG_THRESHOLD)
        meta = memory.get_entry_metadata(entry_id)
        memory.update_entry_metadata(entry_id, {**meta, "feedback_score": -2})

        result = svc.submit_feedback(entry_id, "negative")

        assert result.feedback_score == -3
        assert result.flagged is True
        assert result.deleted is True
        assert memory.get_entry_metadata(entry_id) is None

    def test_flagged_entry_not_served_by_check_cache(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("flagged query", "flagged answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]
        meta = memory.get_entry_metadata(entry_id)
        memory.update_entry_metadata(entry_id, {**meta, "flagged": 1})

        result = memory.check_cache("flagged query")
        assert result is None


class TestSuppression:
    def test_negative_feedback_on_missing_entry_sets_suppression_flag(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        result = svc.submit_feedback("missing-entry-id", "negative")

        assert result.status == "suppressed"
        assert result.feedback_score == 0
        assert result.deleted is False
        # Verify Redis setex was called with correct key pattern
        svc._redis.setex.assert_called_once()
        call_args = svc._redis.setex.call_args[0]
        assert call_args[0] == "skip:missing-entry-id"

    def test_positive_feedback_on_missing_entry_is_noop(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        result = svc.submit_feedback("missing-entry-id", "positive")

        assert result.status == "not_found"
        # No suppression flag should be set
        svc._redis.setex.assert_not_called()

    def test_suppression_flag_key_format(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        svc.submit_feedback("abc123", "negative")

        call_args = svc._redis.setex.call_args[0]
        assert call_args[0] == "skip:abc123"


class TestFeedbackHistory:
    def test_history_returns_events_in_order(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("hist query", "hist answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]

        # Simulate Redis returning 3 stored events
        import json
        events_json = [
            json.dumps({"direction": "positive", "timestamp": "2026-02-19T10:00:00Z"}),
            json.dumps({"direction": "negative", "timestamp": "2026-02-19T10:01:00Z"}),
            json.dumps({"direction": "positive", "timestamp": "2026-02-19T10:02:00Z"}),
        ]
        svc._redis.lrange.return_value = events_json

        result = svc.get_feedback_history(entry_id)

        assert len(result.events) == 3
        assert result.events[0].direction == "positive"
        assert result.events[1].direction == "negative"
        assert result.events[2].direction == "positive"

    def test_history_empty_for_no_feedback(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("empty hist", "empty answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]
        svc._redis.lrange.return_value = []

        result = svc.get_feedback_history(entry_id)

        assert result.events == []
        assert result.feedback_score == 0

    def test_history_404_for_nonexistent_entry(self, tmp_path):
        from fastapi import HTTPException
        svc, _ = _make_service(tmp_path)

        with pytest.raises(HTTPException) as exc_info:
            svc.get_feedback_history("nonexistent-id")
        assert exc_info.value.status_code == 404


class TestRedisUnavailable:
    def test_score_update_succeeds_when_redis_down(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("redis down", "some answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]
        # Simulate Redis being unavailable
        svc._redis = None

        result = svc.submit_feedback(entry_id, "positive")

        assert result.feedback_score == 1
        assert result.status == "ok"

    def test_history_returns_empty_events_when_redis_down(self, tmp_path):
        svc, memory = _make_service(tmp_path)
        memory.store_interaction("redis hist", "some answer", "original", "user1")
        entries = memory.get_all_entries()
        entry_id = entries[0]["id"]
        svc._redis = None

        result = svc.get_feedback_history(entry_id)

        assert result.events == []
        assert result.feedback_score == 0