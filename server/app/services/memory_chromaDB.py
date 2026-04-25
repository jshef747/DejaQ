import hashlib
import time
import logging
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer

from app.config import CHROMA_HOST, CHROMA_PORT

logger = logging.getLogger("dejaq.services.memory_chromaDB")

SIMILARITY_THRESHOLD = 0.15

_embedder: SentenceTransformer | None = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        logger.info("Loading BAAI/bge-small-en-v1.5 embedder...")
        _embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _embedder


def _embed(text: str) -> list[float]:
    return _get_embedder().encode(text, normalize_embeddings=True).tolist()


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

    def check_cache(self, normalized_query: str) -> Optional[tuple[str, str, float]]:
        """Return (generalized_answer, entry_id, distance) on cache hit, None on miss.

        Fetches top-5 candidates, filters to those within SIMILARITY_THRESHOLD,
        then returns the one with the highest score (absent score treated as 0.0).
        """
        start = time.time()
        query_embedding = _embed(normalized_query)
        n = min(5, self._collection.count() or 1)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )

        latency_ms = (time.time() - start) * 1000

        if not (results["distances"] and results["distances"][0] and results["ids"] and results["ids"][0]):
            logger.debug("Cache MISS empty_collection latency=%.1fms", latency_ms)
            return None

        candidates = []
        for i, (dist, entry_id) in enumerate(zip(results["distances"][0], results["ids"][0])):
            if dist <= SIMILARITY_THRESHOLD:
                meta = results["metadatas"][0][i] if results["metadatas"] and results["metadatas"][0] else {}
                score = float(meta.get("score", 0.0))
                candidates.append((score, dist, entry_id, meta))

        if not candidates:
            nearest_dist = results["distances"][0][0]
            logger.debug("Cache MISS distance=%.4f latency=%.1fms", nearest_dist, latency_ms)
            return None

        # Sort by score descending, pick best
        candidates.sort(key=lambda c: c[0], reverse=True)
        best_score, best_dist, best_id, best_meta = candidates[0]
        answer = best_meta["generalized_answer"]
        logger.debug(
            "Cache HIT distance=%.4f score=%.1f threshold=%.2f latency=%.1fms entry_id=%s",
            best_dist,
            best_score,
            SIMILARITY_THRESHOLD,
            latency_ms,
            best_id,
        )
        return answer, best_id, best_dist

    def store_interaction(
        self,
        normalized_query: str,
        generalized_answer: str,
        original_query: str,
        user_id: str,
    ) -> str:
        doc_id = hashlib.sha256(normalized_query.encode()).hexdigest()[:16]
        embedding = _embed(normalized_query)
        self._collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[normalized_query],
            metadatas=[{
                "generalized_answer": generalized_answer,
                "original_query": original_query,
                "user_id": user_id,
                "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "score": 0.0,
                "hit_count": 0,
                "negative_count": 0,
            }],
        )
        logger.info("Stored in cache (id=%s, total=%d)", doc_id, self._collection.count())
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
        """Delete a single cache entry by ID. Returns True if it existed."""
        try:
            existing = self._collection.get(ids=[entry_id])
            if not existing["ids"]:
                return False
            self._collection.delete(ids=[entry_id])
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
