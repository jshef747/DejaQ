import pytest

from app.services.memory_chromaDB import MemoryService

pytestmark = pytest.mark.no_model


def _make_svc(collection_name: str) -> MemoryService:
    """Create a MemoryService against the running ChromaDB instance."""
    return MemoryService(collection_name=collection_name)


def _chroma_available() -> bool:
    try:
        svc = _make_svc("_probe")
        svc.count  # noqa: B018
        return True
    except Exception:
        return False


chroma_required = pytest.mark.skipif(
    not _chroma_available(),
    reason="ChromaDB server not available",
)


@chroma_required
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
        answer, entry_id, distance = result
        assert "Paris" in answer
        assert entry_id is not None
        assert isinstance(distance, float)

    def test_cache_miss_for_unrelated(self, memory_service):
        memory_service.store_interaction(
            normalized_query="capital of france",
            generalized_answer="The capital of France is Paris.",
            original_query="what's the capital of france?",
            user_id="test-user",
        )
        result = memory_service.check_cache("how does photosynthesis work")
        assert result is None


@chroma_required
class TestCount:
    def test_empty_count(self):
        svc = _make_svc("empty_test")
        assert svc.count == 0

    def test_count_after_store(self):
        svc = _make_svc("count_test")
        svc.store_interaction("q1", "a1", "orig1", "user1")
        assert svc.count >= 1

    def test_upsert_same_key(self):
        svc = _make_svc("upsert_test")
        svc.store_interaction("same query upsert", "answer1", "orig1", "user1")
        before = svc.count
        svc.store_interaction("same query upsert", "answer2", "orig2", "user2")
        assert svc.count == before  # upsert, not insert


@chroma_required
class TestGetAllEntries:
    def test_empty_returns_empty_list(self):
        svc = _make_svc("entries_empty_test")
        assert svc.get_all_entries() == []

    def test_returns_stored_entries(self):
        svc = _make_svc("entries_test")
        svc.store_interaction("test query entries", "test answer", "original", "user1")
        entries = svc.get_all_entries()
        assert len(entries) >= 1
        ids = [e["normalized_query"] for e in entries]
        assert "test query entries" in ids


@chroma_required
class TestDeleteEntry:
    def test_delete_existing(self):
        svc = _make_svc("delete_test")
        svc.store_interaction("query to delete", "answer", "orig", "user1")
        entries = svc.get_all_entries()
        entry_id = next(e["id"] for e in entries if e["normalized_query"] == "query to delete")
        assert svc.delete_entry(entry_id) is True

    def test_delete_nonexistent(self):
        svc = _make_svc("delete_none_test")
        assert svc.delete_entry("nonexistent-id-xyz") is False


@chroma_required
class TestCheckCacheReturnType:
    def test_check_cache_returns_tuple_on_hit(self):
        svc = _make_svc("ret_type_hit")
        svc.store_interaction("capital of france", "Paris is the capital.", "what is the capital?", "u1")
        result = svc.check_cache("capital of france")
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 3
        answer, entry_id, distance = result
        assert "Paris" in answer
        assert isinstance(entry_id, str)
        assert isinstance(distance, float)

    def test_check_cache_returns_none_on_miss(self):
        svc = _make_svc("ret_type_miss")
        svc.store_interaction("capital of france", "Paris is the capital.", "what is the capital?", "u1")
        result = svc.check_cache("how does photosynthesis work")
        assert result is None


@chroma_required
class TestThreshold:
    def test_entry_below_threshold_hits(self):
        from unittest.mock import patch

        svc = _make_svc("thresh_hit")
        svc.store_interaction("capital of france", "Paris is the capital.", "original", "u1")

        original_query = svc._collection.query

        def patched_query(**kwargs):
            result = original_query(**kwargs)
            if result["distances"] and result["distances"][0]:
                result["distances"][0][0] = 0.10  # well within 0.15 threshold
            return result

        with patch.object(svc._collection, "query", side_effect=patched_query):
            result = svc.check_cache("capital of france")

        assert result is not None, "Entry at distance 0.10 should hit (below 0.15 threshold)"

    def test_entry_above_threshold_misses(self):
        from unittest.mock import patch

        svc = _make_svc("thresh_miss")
        svc.store_interaction("capital of france", "Paris is the capital.", "original", "u1")

        original_query = svc._collection.query

        def patched_query(**kwargs):
            result = original_query(**kwargs)
            if result["distances"] and result["distances"][0]:
                result["distances"][0][0] = 0.18  # above 0.15 threshold
            return result

        with patch.object(svc._collection, "query", side_effect=patched_query):
            result = svc.check_cache("capital of france")

        assert result is None, "Entry at distance 0.18 should miss (above 0.15 threshold)"
