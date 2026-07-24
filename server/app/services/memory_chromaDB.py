import hashlib
import time
import logging
from dataclasses import dataclass
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer

from app.config import (
    CACHE_BAND_MAX_DISTANCE,
    CACHE_RESCUE_ENABLED,
    CACHE_RESCUE_MAX_DISTANCE,
    CACHE_TRUST_DISTANCE,
    CHROMA_HOST,
    CHROMA_PORT,
)
from app.services.lexical_match import align

logger = logging.getLogger("dejaq.services.memory_chromaDB")

# Back-compat alias — the trusted-zone ceiling. Distances at or below this are
# served directly; the (trust, band_max] range is the validator-guarded band.
SIMILARITY_THRESHOLD = CACHE_TRUST_DISTANCE

# Candidates returned per lookup from ChromaDB. 10 (not 5) because the lexical
# rescue tier needs the clean twin of a heavily typo'd query inside top-K even
# when the embedding ranks it low.
_LOOKUP_N_RESULTS = 10

_embedder: SentenceTransformer | None = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        logger.info("Loading BAAI/bge-small-en-v1.5 embedder...")
        _embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _embedder


def _embed(text: str) -> list[float]:
    return _get_embedder().encode(text, normalize_embeddings=True).tolist()


@dataclass(frozen=True)
class CacheLookupResult:
    hit: bool
    generalized_answer: str | None = None
    entry_id: str | None = None
    distance: float | None = None
    matched_query: str | None = None
    nearest_distance: float | None = None
    nearest_prompt: str | None = None
    # True when the hit came from the validator-guarded band (trust, band_max].
    # The caller must run the cache validator before serving it.
    requires_validation: bool = False
    # True when the hit came from the lexical-rescue tier (past the band, but
    # word-aligned with the stored query). Always requires validation.
    rescued: bool = False
    # Word pairs where the query and the matched stored query differ
    # semantically (e.g. (("list", "string"),)) — a hint for the validator.
    # None when the words aligned or alignment wasn't informative.
    mismatches: tuple[tuple[str, str], ...] | None = None
    # Image fingerprints of the matched entry (present only for image entries).
    # Carried here from the entry metadata read during lookup so the router's
    # image gate needs no extra Chroma round-trip.
    image_dhash: str | None = None
    image_clip: str | None = None


class MemoryService:
    def __init__(
        self,
        collection_name: str = "dejaq_default",
    ):
        logger.info("Initializing ChromaDB (collection=%s, host=%s, port=%d)", collection_name, CHROMA_HOST, CHROMA_PORT)
        self._client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        # No embedding_function — we embed manually and pass query_embeddings / embeddings directly.
        # This avoids any conflict with a previously persisted embedding function config.
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB ready — %d documents in collection '%s'", self._collection.count(), collection_name)

    def lookup_cache(self, normalized_query: str) -> CacheLookupResult:
        """Return cache hit details plus nearest Chroma prompt/distance.

        Three tiers, in priority order:
        - trusted (distance ≤ CACHE_TRUST_DISTANCE): served directly,
        - band (≤ CACHE_BAND_MAX_DISTANCE): served only if the validator accepts,
        - lexical rescue (≤ CACHE_RESCUE_MAX_DISTANCE and word-aligned with the
          stored query — a heavily typo'd variant): validator-gated as well.
        Within a tier, highest score wins (absent score treated as 0.0).
        """
        start = time.time()
        query_embedding = _embed(normalized_query)
        n = min(_LOOKUP_N_RESULTS, self._collection.count() or 1)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )

        latency_ms = (time.time() - start) * 1000
        band_ceiling = max(CACHE_TRUST_DISTANCE, CACHE_BAND_MAX_DISTANCE)

        if not (results["distances"] and results["distances"][0] and results["ids"] and results["ids"][0]):
            logger.debug("Cache MISS empty_collection latency=%.1fms", latency_ms)
            return CacheLookupResult(hit=False)

        nearest_dist = float(results["distances"][0][0])
        nearest_prompt = None
        if results["documents"] and results["documents"][0]:
            nearest_prompt = results["documents"][0][0] or None

        trusted: list[tuple] = []
        band: list[tuple] = []
        rescue: list[tuple] = []
        for i, (dist, entry_id) in enumerate(zip(results["distances"][0], results["ids"][0])):
            dist = float(dist)
            meta = results["metadatas"][0][i] if results["metadatas"] and results["metadatas"][0] else {}
            score = float(meta.get("score", 0.0))
            matched_query = ""
            if results["documents"] and results["documents"][0]:
                matched_query = results["documents"][0][i] or ""
            row = (score, dist, entry_id, meta, matched_query)
            if dist <= CACHE_TRUST_DISTANCE:
                trusted.append(row)
            elif dist <= band_ceiling:
                band.append(row)
            elif (
                CACHE_RESCUE_ENABLED
                and dist <= CACHE_RESCUE_MAX_DISTANCE
                and matched_query
                and align(normalized_query, matched_query).aligned
            ):
                rescue.append(row)

        if not trusted and not band and not rescue:
            logger.debug("Cache MISS distance=%.4f latency=%.1fms", nearest_dist, latency_ms)
            return CacheLookupResult(
                hit=False,
                nearest_distance=nearest_dist,
                nearest_prompt=nearest_prompt,
            )

        pool = trusted or band or rescue
        requires_validation = not trusted
        rescued = not trusted and not band
        pool.sort(key=lambda r: r[0], reverse=True)
        best_score, best_dist, best_id, best_meta, matched_query = pool[0]
        answer = best_meta["generalized_answer"]

        # Word-level mismatches vs the chosen entry — validator hint for the
        # single-word-swap trap (list/string). Only informative when the words
        # DIDN'T align; rescued hits aligned by construction.
        mismatches: tuple[tuple[str, str], ...] | None = None
        if not rescued and matched_query:
            align_result = align(normalized_query, matched_query)
            if not align_result.aligned and align_result.mismatches:
                mismatches = align_result.mismatches

        logger.debug(
            "Cache HIT distance=%.4f score=%.1f trust=%.2f band_max=%.2f "
            "requires_validation=%s rescued=%s latency=%.1fms entry_id=%s",
            best_dist,
            best_score,
            CACHE_TRUST_DISTANCE,
            CACHE_BAND_MAX_DISTANCE,
            requires_validation,
            rescued,
            latency_ms,
            best_id,
        )
        return CacheLookupResult(
            hit=True,
            generalized_answer=answer,
            entry_id=best_id,
            distance=best_dist,
            matched_query=matched_query,
            nearest_distance=nearest_dist,
            nearest_prompt=nearest_prompt,
            requires_validation=requires_validation,
            rescued=rescued,
            mismatches=mismatches,
            image_dhash=best_meta.get("image_dhash"),
            image_clip=best_meta.get("image_clip"),
        )

    def check_cache(self, normalized_query: str) -> Optional[tuple[str, str, float, str]]:
        """Return (generalized_answer, entry_id, distance, matched_query) on cache hit, None on miss.

        Legacy helper — only returns trusted-zone hits. Band hits (which need
        validation) are reported as a miss so old callers keep their prior semantics.
        """
        result = self.lookup_cache(normalized_query)
        if not result.hit or result.requires_validation:
            return None
        return (
            result.generalized_answer or "",
            result.entry_id or "",
            float(result.distance or 0.0),
            result.matched_query or "",
        )

    def store_interaction(
        self,
        normalized_query: str,
        generalized_answer: str,
        original_query: str,
        user_id: str,
        image_dhash: str | None = None,
        image_clip: str | None = None,
    ) -> str:
        doc_id = hashlib.sha256(normalized_query.encode()).hexdigest()[:16]
        embedding = _embed(normalized_query)
        metadata = {
            "generalized_answer": generalized_answer,
            "original_query": original_query,
            "user_id": user_id,
            "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "score": 0.0,
            "hit_count": 0,
            "negative_count": 0,
        }
        # Image fingerprints only present for image requests; Chroma metadata is
        # per-entry, so text entries simply omit these keys (no schema change).
        if image_dhash and image_clip:
            metadata["image_dhash"] = image_dhash
            metadata["image_clip"] = image_clip
        self._collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[normalized_query],
            metadatas=[metadata],
        )
        logger.info("Stored in cache (id=%s, total=%d)", doc_id, self._collection.count())
        return doc_id

    def store_alias(self, alias_query: str, source_entry_id: str) -> str | None:
        """Store a typo'd phrasing as an alias entry pointing at an existing answer.

        Called after the validator accepts a band/rescue hit: the alias makes the
        same typo an instant trusted hit next time. Chains are flattened — an
        alias of an alias points at the root entry.
        Returns the alias doc id, or None when there is nothing to store.
        """
        parent_meta = self.get_entry_metadata(source_entry_id)
        if parent_meta is None:
            logger.warning("store_alias: source entry %s not found", source_entry_id)
            return None
        root_id = parent_meta.get("alias_of") or source_entry_id

        doc_id = hashlib.sha256(alias_query.encode()).hexdigest()[:16]
        if doc_id == source_entry_id or doc_id == root_id:
            return None  # alias text identical to the stored query

        self._collection.upsert(
            ids=[doc_id],
            embeddings=[_embed(alias_query)],
            documents=[alias_query],
            metadatas=[{
                "generalized_answer": parent_meta.get("generalized_answer", ""),
                "original_query": parent_meta.get("original_query", ""),
                "user_id": parent_meta.get("user_id", ""),
                "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "score": 0.0,
                "hit_count": 0,
                "negative_count": 0,
                "alias_of": root_id,
            }],
        )
        logger.info("Stored alias %s -> %s (query=%r)", doc_id, root_id, alias_query[:60])
        return doc_id

    def get_all_entries(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return all cached entries with metadata for the cache viewer."""
        total = self._collection.count()
        if total == 0:
            return []

        results = self._collection.get(
            include=["documents", "metadatas"],
            limit=limit,
            offset=offset,
        )

        entries = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i] if results["metadatas"] else {}
            entries.append({
                "id": doc_id,
                "normalized_query": results["documents"][i] if results["documents"] else "",
                "generalized_answer": meta.get("generalized_answer", ""),
                "original_query": meta.get("original_query", ""),
                "user_id": meta.get("user_id", ""),
                "stored_at": meta.get("stored_at", ""),
            })

        return entries

    def increment_hit_count(self, doc_id: str) -> None:
        """Increment hit_count metadata field. Read-modify-write; raises KeyError if not found."""
        meta = self.get_entry_metadata(doc_id)
        if meta is None:
            raise KeyError(doc_id)
        meta["hit_count"] = int(meta.get("hit_count", 0)) + 1
        self._collection.update(ids=[doc_id], metadatas=[meta])

    def get_negative_count(self, doc_id: str) -> int:
        """Return negative_count for an entry (0 if absent). Raises KeyError if doc not found."""
        meta = self.get_entry_metadata(doc_id)
        if meta is None:
            raise KeyError(doc_id)
        return int(meta.get("negative_count", 0))

    def update_score(self, doc_id: str, delta: float) -> float:
        """Apply delta to score and increment negative_count (for negative deltas). Returns new score.

        Raises KeyError if doc not found. Uses read-modify-write; concurrent updates may lose counts.
        """
        meta = self.get_entry_metadata(doc_id)
        if meta is None:
            raise KeyError(doc_id)
        new_score = float(meta.get("score", 0.0)) + delta
        meta["score"] = new_score
        if delta < 0:
            meta["negative_count"] = int(meta.get("negative_count", 0)) + 1
        self._collection.update(ids=[doc_id], metadatas=[meta])
        logger.info("Updated score for %s: delta=%.1f new_score=%.1f", doc_id, delta, new_score)
        return new_score

    def delete_entry(self, entry_id: str) -> bool:
        """Delete a cache entry by ID, cascading to its aliases. Returns True if it existed."""
        try:
            existing = self._collection.get(ids=[entry_id])
            if not existing["ids"]:
                return False
            self._collection.delete(ids=[entry_id])
            # Cascade: aliases point at a deleted answer — remove them too.
            try:
                dependents = self._collection.get(where={"alias_of": entry_id}, include=[])
                if dependents["ids"]:
                    self._collection.delete(ids=dependents["ids"])
                    logger.info("Deleted %d alias(es) of %s", len(dependents["ids"]), entry_id)
            except Exception:
                logger.warning("Alias cascade failed for %s", entry_id, exc_info=True)
            logger.info("Deleted cache entry %s (total=%d)", entry_id, self._collection.count())
            return True
        except Exception:
            logger.error("Failed to delete cache entry %s", entry_id)
            return False

    def evict_below_floor(self, floor: float) -> int:
        """Delete all entries with score < floor. Returns count of deleted entries."""
        try:
            results = self._collection.get(
                where={"score": {"$lt": floor}},
                include=[],
            )
            ids_to_delete = results["ids"]
            if not ids_to_delete:
                return 0
            self._collection.delete(ids=ids_to_delete)
            logger.info("Evicted %d entries below score floor %.1f", len(ids_to_delete), floor)
            return len(ids_to_delete)
        except Exception:
            logger.error("evict_below_floor failed", exc_info=True)
            return 0

    def get_entry_metadata(self, entry_id: str) -> Optional[dict]:
        """Return full metadata dict for a cache entry, or None if not found."""
        result = self._collection.get(ids=[entry_id], include=["metadatas"])
        if not result["ids"]:
            return None
        return result["metadatas"][0]

    def update_entry_metadata(self, entry_id: str, metadata: dict) -> bool:
        """Replace the full metadata for a cache entry. ChromaDB requires the complete dict."""
        try:
            self._collection.update(ids=[entry_id], metadatas=[metadata])
            logger.info("Updated metadata for cache entry %s", entry_id)
            return True
        except Exception:
            logger.error("Failed to update metadata for entry %s", entry_id, exc_info=True)
            return False

    @property
    def count(self) -> int:
        return self._collection.count()


# ---------------------------------------------------------------------------
# Namespace-aware pool — lazy, one MemoryService per ChromaDB collection name
# ---------------------------------------------------------------------------

_pool: dict[str, "MemoryService"] = {}


def get_memory_service(namespace: str = "dejaq_default") -> "MemoryService":
    """Return a cached MemoryService for the given namespace (ChromaDB collection name).

    Creates a new instance on first access; subsequent calls for the same namespace
    return the same instance without re-initializing the ChromaDB collection.
    """
    if namespace not in _pool:
        _pool[namespace] = MemoryService(collection_name=namespace)
    return _pool[namespace]
