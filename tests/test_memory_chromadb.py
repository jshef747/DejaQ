import pytest

from app.services.memory_chromaDB import MemoryService

pytestmark = pytest.mark.no_model


class TestCacheHitMiss:
    def test_store_then_cache_hit(self, memory_service):
        memory_service.store_interaction(
            normalized_query="capital of france",
            generalized_answer="The capital of France is Paris.",
            original_query="what's the capital of france?",
            user_id="test-user",
        )
        result = memory_service.check_cache("capital of france")
        assert result is not None
        answer, entry_id = result
        assert "Paris" in answer
        assert entry_id is not None

    def test_cache_miss_for_unrelated(self, memory_service):
        memory_service.store_interaction(
            normalized_query="capital of france",
            generalized_answer="The capital of France is Paris.",
            original_query="what's the capital of france?",
            user_id="test-user",
        )
        result = memory_service.check_cache("how does photosynthesis work")
        assert result is None


class TestCount:
    def test_empty_count(self, tmp_path):
        svc = MemoryService(
            collection_name="empty_test",
            persist_directory=str(tmp_path / "empty"),
        )
        assert svc.count == 0

    def test_count_after_store(self, tmp_path):
        svc = MemoryService(
            collection_name="count_test",
            persist_directory=str(tmp_path / "count"),
        )
        svc.store_interaction("q1", "a1", "orig1", "user1")
        assert svc.count == 1

    def test_upsert_same_key(self, tmp_path):
        svc = MemoryService(
            collection_name="upsert_test",
            persist_directory=str(tmp_path / "upsert"),
        )
        svc.store_interaction("same query", "answer1", "orig1", "user1")
        svc.store_interaction("same query", "answer2", "orig2", "user2")
        assert svc.count == 1


class TestGetAllEntries:
    def test_empty_returns_empty_list(self, tmp_path):
        svc = MemoryService(
            collection_name="entries_empty",
            persist_directory=str(tmp_path / "entries_empty"),
        )
        assert svc.get_all_entries() == []

    def test_returns_stored_entries(self, tmp_path):
        svc = MemoryService(
            collection_name="entries_test",
            persist_directory=str(tmp_path / "entries"),
        )
        svc.store_interaction("test query", "test answer", "original", "user1")
        entries = svc.get_all_entries()
        assert len(entries) == 1
        assert entries[0]["normalized_query"] == "test query"
        assert entries[0]["generalized_answer"] == "test answer"


class TestDeleteEntry:
    def test_delete_existing(self, tmp_path):
        svc = MemoryService(
            collection_name="delete_test",
            persist_directory=str(tmp_path / "delete"),
        )
        svc.store_interaction("query to delete", "answer", "orig", "user1")
        entries = svc.get_all_entries()
        entry_id = entries[0]["id"]
        assert svc.delete_entry(entry_id) is True
        assert svc.count == 0

    def test_delete_nonexistent(self, tmp_path):
        svc = MemoryService(
            collection_name="delete_none",
            persist_directory=str(tmp_path / "delete_none"),
        )
        assert svc.delete_entry("nonexistent-id") is False


class TestCheckCacheReturnType:
    def test_check_cache_returns_tuple_on_hit(self, tmp_path):
        svc = MemoryService(
            collection_name="ret_type_hit",
            persist_directory=str(tmp_path / "ret_type_hit"),
        )
        svc.store_interaction("capital of france", "Paris is the capital.", "what is the capital?", "u1")
        result = svc.check_cache("capital of france")
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2
        answer, entry_id = result
        assert "Paris" in answer
        assert isinstance(entry_id, str)

    def test_check_cache_returns_none_on_miss(self, tmp_path):
        svc = MemoryService(
            collection_name="ret_type_miss",
            persist_directory=str(tmp_path / "ret_type_miss"),
        )
        svc.store_interaction("capital of france", "Paris is the capital.", "what is the capital?", "u1")
        result = svc.check_cache("how does photosynthesis work")
        assert result is None

    def test_flagged_entry_returns_none(self, tmp_path):
        svc = MemoryService(
            collection_name="ret_type_flagged",
            persist_directory=str(tmp_path / "ret_type_flagged"),
        )
        svc.store_interaction("capital of france", "Paris is the capital.", "what is the capital?", "u1")
        entries = svc.get_all_entries()
        entry_id = entries[0]["id"]
        # Flag the entry
        meta = svc.get_entry_metadata(entry_id)
        svc.update_entry_metadata(entry_id, {**meta, "flagged": 1})
        # Exact-match query should still return None because entry is flagged
        result = svc.check_cache("capital of france")
        assert result is None


class TestDynamicThreshold:
    def test_trusted_entry_uses_relaxed_threshold(self, tmp_path):
        """An entry with feedback_score >= TRUSTED_THRESHOLD should use the relaxed ceiling."""
        from unittest.mock import patch
        from app.services import memory_chromaDB as mem_mod

        svc = MemoryService(
            collection_name="dyn_thresh_trusted",
            persist_directory=str(tmp_path / "dyn_thresh_trusted"),
        )
        svc.store_interaction("capital of france", "Paris is the capital.", "original", "u1")
        entries = svc.get_all_entries()
        entry_id = entries[0]["id"]
        meta = svc.get_entry_metadata(entry_id)
        # Boost score to trusted threshold
        svc.update_entry_metadata(entry_id, {**meta, "feedback_score": 3})

        # Patch the query to return a distance of 0.18 (above default 0.15, below relaxed 0.20)
        original_query = svc._collection.query

        def patched_query(**kwargs):
            result = original_query(**kwargs)
            if result["distances"] and result["distances"][0]:
                result["distances"][0][0] = 0.18
            return result

        with patch.object(svc._collection, "query", side_effect=patched_query):
            result = svc.check_cache("capital of france")

        assert result is not None, "Trusted entry should match at distance 0.18 with relaxed threshold"

    def test_neutral_entry_uses_default_threshold(self, tmp_path):
        """An entry with feedback_score=0 must not match at distance 0.18 (above default 0.15)."""
        from unittest.mock import patch

        svc = MemoryService(
            collection_name="dyn_thresh_neutral",
            persist_directory=str(tmp_path / "dyn_thresh_neutral"),
        )
        svc.store_interaction("capital of france", "Paris is the capital.", "original", "u1")

        original_query = svc._collection.query

        def patched_query(**kwargs):
            result = original_query(**kwargs)
            if result["distances"] and result["distances"][0]:
                result["distances"][0][0] = 0.18
            return result

        with patch.object(svc._collection, "query", side_effect=patched_query):
            result = svc.check_cache("capital of france")

        assert result is None, "Neutral entry should NOT match at distance 0.18 with default threshold"
