import hashlib

import pytest

from app.services.memory_chromaDB import MemoryService

pytestmark = pytest.mark.no_model


def _make_svc(collection_name: str) -> MemoryService:
    """Create a MemoryService against the running ChromaDB instance."""
    return MemoryService(collection_name=collection_name)


def _chroma_available() -> bool:
    try:
        svc = _make_svc("probe_test")
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
        answer, entry_id, distance, matched_query = result
        assert "Paris" in answer
        assert entry_id is not None
        assert isinstance(distance, float)
        assert matched_query == "capital of france"

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
        assert len(result) == 4
        answer, entry_id, distance, matched_query = result
        assert "Paris" in answer
        assert isinstance(entry_id, str)
        assert isinstance(distance, float)
        assert matched_query == "capital of france"

    def test_check_cache_returns_none_on_miss(self):
        svc = _make_svc("ret_type_miss")
        svc.store_interaction("capital of france", "Paris is the capital.", "what is the capital?", "u1")
        result = svc.check_cache("how does photosynthesis work")
        assert result is None

    def test_lookup_cache_returns_nearest_prompt_on_miss(self):
        svc = _make_svc("lookup_nearest_miss")
        svc.store_interaction("capital of france", "Paris is the capital.", "what is the capital?", "u1")
        result = svc.lookup_cache("how does photosynthesis work")

        assert result.hit is False
        assert result.generalized_answer is None
        assert result.entry_id is None
        assert result.nearest_distance is not None
        assert result.nearest_prompt == "capital of france"

    def test_lookup_cache_empty_collection_has_no_nearest_prompt(self):
        svc = _make_svc("lookup_empty")
        result = svc.lookup_cache("how does photosynthesis work")

        assert result.hit is False
        assert result.nearest_distance is None
        assert result.nearest_prompt is None


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
                result["distances"][0][0] = 0.18  # in the validator band — not a trusted hit
            return result

        with patch.object(svc._collection, "query", side_effect=patched_query):
            result = svc.check_cache("capital of france")

        assert result is None, "check_cache must exclude band hits (0.18 > trust 0.15)"


def _force_distances(svc, per_probe):
    """Patch svc._collection.query to overwrite distances[probe_idx][0] with given values.

    per_probe: list of distances, one per query embedding (probe). Missing probes
    keep their real distance.
    """
    from unittest.mock import patch

    original_query = svc._collection.query

    def patched_query(**kwargs):
        result = original_query(**kwargs)
        for p_idx, dist in enumerate(per_probe):
            if dist is None:
                continue
            if result["distances"] and len(result["distances"]) > p_idx and result["distances"][p_idx]:
                result["distances"][p_idx][0] = dist
        return result

    return patch.object(svc._collection, "query", side_effect=patched_query)


@chroma_required
class TestBand:
    def test_trusted_hit_no_validation(self):
        svc = _make_svc("band_trusted")
        svc.store_interaction("capital of france", "Paris is the capital.", "orig", "u1")
        with _force_distances(svc, [0.10]):
            result = svc.lookup_cache("capital of france")
        assert result.hit is True
        assert result.requires_validation is False

    def test_trusted_hit_on_identical_words_is_lexically_exact(self):
        svc = _make_svc("band_trusted_exact")
        svc.store_interaction("capital of france", "Paris is the capital.", "orig", "u1")
        with _force_distances(svc, [0.01]):
            result = svc.lookup_cache("capital of france")
        assert result.lexically_exact is True

    def test_near_duplicate_distance_entity_swap_is_not_lexically_exact(self):
        """dejaq-acceptance-fixes report, defect #2: "מה בירת אוסטריה?"
        (capital of Austria) vs "מה בירת אוסטרליה?" (capital of Australia)
        measured distance 0.0023 in production - inside VALIDATOR_SKIP_DISTANCE,
        where the trust tier used to skip the validator outright on distance
        alone. align() calls the two country names "aligned" (they fuzzy-match
        at 0.93 letter-similarity) so `mismatches` alone doesn't catch it either
        - lexically_exact is the signal that does, and is what the caller
        (openai_compat.py) now additionally requires before skipping
        validation."""
        svc = _make_svc("band_trusted_entity_swap")
        svc.store_interaction("what is the capital of austria", "Vienna is the capital of Austria.", "orig", "u1")
        with _force_distances(svc, [0.0023]):
            result = svc.lookup_cache("what is the capital of australia")
        assert result.hit is True
        assert result.requires_validation is False  # still trust-tier by distance
        assert result.lexically_exact is False  # but not safe to skip the validator

    def test_band_hit_requires_validation(self):
        svc = _make_svc("band_hit")
        svc.store_interaction("capital of france", "Paris is the capital.", "orig", "u1")
        with _force_distances(svc, [0.18]):
            result = svc.lookup_cache("capital of france")
        assert result.hit is True
        assert result.requires_validation is True
        assert result.distance == 0.18

    def test_above_band_misses(self):
        # Word-different query past the band: neither band nor rescue applies.
        svc = _make_svc("band_above")
        svc.store_interaction("capital of france", "Paris is the capital.", "orig", "u1")
        with _force_distances(svc, [0.30]):
            result = svc.lookup_cache("how does photosynthesis work")
        assert result.hit is False
        assert result.nearest_distance == 0.30

    def test_band_disabled_via_config(self, monkeypatch):
        import app.services.memory_chromaDB as mem

        monkeypatch.setattr(mem, "CACHE_BAND_MAX_DISTANCE", 0.15)  # ≤ trust → band off
        monkeypatch.setattr(mem, "CACHE_RESCUE_ENABLED", False)
        svc = _make_svc("band_disabled")
        svc.store_interaction("capital of france", "Paris is the capital.", "orig", "u1")
        with _force_distances(svc, [0.18]):
            result = svc.lookup_cache("capital of france")
        assert result.hit is False, "0.18 must miss when band and rescue are disabled"

    def test_check_cache_excludes_band(self):
        svc = _make_svc("band_check_cache")
        svc.store_interaction("capital of france", "Paris is the capital.", "orig", "u1")
        with _force_distances(svc, [0.18]):
            assert svc.check_cache("capital of france") is None


@chroma_required
class TestLexicalRescue:
    def test_aligned_typo_past_band_is_rescued(self):
        svc = _make_svc("rescue_hit")
        svc.store_interaction("what is the capital of russia?", "Moscow.", "orig", "u1")
        with _force_distances(svc, [0.40]):
            result = svc.lookup_cache("what is teh captial of rusia?")
        assert result.hit is True
        assert result.rescued is True
        assert result.requires_validation is True

    def test_non_aligned_past_band_misses(self):
        svc = _make_svc("rescue_veto")
        svc.store_interaction("what is the capital of france?", "Paris.", "orig", "u1")
        with _force_distances(svc, [0.40]):
            result = svc.lookup_cache("what is the capital of germany?")
        assert result.hit is False

    def test_aligned_beyond_rescue_max_misses(self):
        svc = _make_svc("rescue_too_far")
        svc.store_interaction("what is the capital of russia?", "Moscow.", "orig", "u1")
        with _force_distances(svc, [0.70]):
            result = svc.lookup_cache("what is teh captial of rusia?")
        assert result.hit is False

    def test_rescue_disabled_via_config(self, monkeypatch):
        import app.services.memory_chromaDB as mem

        monkeypatch.setattr(mem, "CACHE_RESCUE_ENABLED", False)
        svc = _make_svc("rescue_disabled")
        svc.store_interaction("what is the capital of russia?", "Moscow.", "orig", "u1")
        with _force_distances(svc, [0.40]):
            result = svc.lookup_cache("what is teh captial of rusia?")
        assert result.hit is False

    def test_band_hit_carries_mismatches_hint(self):
        svc = _make_svc("band_mismatch_hint")
        svc.store_interaction("how do i reverse a string in python?", "Use s[::-1].", "orig", "u1")
        with _force_distances(svc, [0.18]):
            result = svc.lookup_cache("how do i reverse a list in python?")
        assert result.hit is True
        assert result.requires_validation is True
        assert result.mismatches is not None
        assert ("list", "string") in result.mismatches


@chroma_required
class TestAliases:
    def test_store_alias_roundtrip(self):
        svc = _make_svc("alias_roundtrip")
        parent_id = svc.store_interaction(
            "what is the capital of russia?", "Moscow.", "orig", "u1"
        )
        alias_id = svc.store_alias("what is teh captial of rusia?", parent_id)
        assert alias_id is not None and alias_id != parent_id
        meta = svc.get_entry_metadata(alias_id)
        assert meta["alias_of"] == parent_id
        assert meta["generalized_answer"] == "Moscow."
        # alias is a real entry: exact repeat of the typo is now a trusted hit
        result = svc.lookup_cache("what is teh captial of rusia?")
        assert result.hit is True
        assert result.requires_validation is False

    def test_alias_chain_flattens_to_root(self):
        svc = _make_svc("alias_chain")
        root_id = svc.store_interaction("what is the capital of russia?", "Moscow.", "orig", "u1")
        alias1 = svc.store_alias("what is teh capital of rusia?", root_id)
        alias2 = svc.store_alias("wat is teh captial of rusia?", alias1)
        assert svc.get_entry_metadata(alias2)["alias_of"] == root_id

    def test_store_alias_missing_parent_returns_none(self):
        svc = _make_svc("alias_orphan")
        assert svc.store_alias("some query", "nonexistent-id") is None

    def test_delete_entry_cascades_aliases(self):
        svc = _make_svc("alias_cascade")
        parent_id = svc.store_interaction("what is the capital of russia?", "Moscow.", "orig", "u1")
        alias_id = svc.store_alias("what is teh captial of rusia?", parent_id)
        assert svc.delete_entry(parent_id) is True
        assert svc.get_entry_metadata(alias_id) is None


@chroma_required
class TestEvictBelowFloorCascade:
    def test_evicting_a_root_removes_its_aliases(self):
        """B11 regression: evict_below_floor used to bulk-delete via
        self._collection.delete directly, bypassing delete_entry's alias
        cascade - an evicted root left orphan aliases still serving its
        copied answer. It must now route through delete_entry."""
        svc = _make_svc("evict_cascade")
        parent_id = svc.store_interaction("what is the capital of russia?", "Moscow.", "orig", "u1")
        alias_id = svc.store_alias("what is teh captial of rusia?", parent_id)

        meta = svc.get_entry_metadata(parent_id)
        meta["score"] = -10.0
        svc.update_entry_metadata(parent_id, meta)

        deleted = svc.evict_below_floor(-5.0)

        assert deleted == 1
        assert svc.get_entry_metadata(parent_id) is None
        assert svc.get_entry_metadata(alias_id) is None

    def test_entries_at_or_above_the_floor_survive(self):
        svc = _make_svc("evict_survivor")
        survivor_id = svc.store_interaction("what is the capital of france?", "Paris.", "orig", "u1")

        deleted = svc.evict_below_floor(-5.0)

        assert deleted == 0
        assert svc.get_entry_metadata(survivor_id) is not None


@chroma_required
class TestStoreAliasRace:
    def test_alias_does_not_survive_a_parent_deleted_mid_store(self, monkeypatch):
        """B12 regression: store_alias runs fire-and-forget after the
        response is sent; if the parent is deleted (negative feedback)
        between the get_entry_metadata read and the upsert, the alias used
        to be written as an orphan carrying the just-deleted answer. Now the
        parent's existence is re-verified after the upsert and the alias is
        removed if the parent is gone."""
        svc = _make_svc("alias_race")
        parent_id = svc.store_interaction("what is the capital of russia?", "Moscow.", "orig", "u1")

        original_upsert = svc._collection.upsert

        def racing_upsert(*args, **kwargs):
            # Simulate a negative-feedback delete landing between the parent
            # read in store_alias and this upsert actually committing.
            svc.delete_entry(parent_id)
            return original_upsert(*args, **kwargs)

        monkeypatch.setattr(svc._collection, "upsert", racing_upsert)

        alias_query = "what is teh captial of rusia?"
        alias_id = svc.store_alias(alias_query, parent_id)

        assert alias_id is None
        assert svc.get_entry_metadata(parent_id) is None
        expected_alias_id = hashlib.sha256(alias_query.encode()).hexdigest()[:16]
        assert svc.get_entry_metadata(expected_alias_id) is None
