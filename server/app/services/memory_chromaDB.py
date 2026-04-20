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
        """Return (generalized_answer, entry_id, distance) on cache hit, None on miss."""
        start = time.time()
        query_embedding = _embed(normalized_query)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )

        latency_ms = (time.time() - start) * 1000

        if (
            results["distances"]
            and results["distances"][0]
            and results["ids"]
            and results["ids"][0]
        ):
            distance = results["distances"][0][0]
            meta = results["metadatas"][0][0] if results["metadatas"] and results["metadatas"][0] else {}
            entry_id = results["ids"][0][0]

            # TODO: feedback-driven threshold relaxation will be reintroduced pre-BC6
            if distance <= SIMILARITY_THRESHOLD:
                answer = meta["generalized_answer"]
                logger.info(
                    "Cache HIT (distance=%.4f, threshold=%.2f, latency=%.1fms) for query: %s",
                    distance, SIMILARITY_THRESHOLD, latency_ms, normalized_query,
                )
                return answer, entry_id, distance

        distance = results["distances"][0][0] if results["distances"] and results["distances"][0] else None
        logger.info(
            "Cache MISS (distance=%s, latency=%.1fms) for query: %s",
            f"{distance:.4f}" if distance is not None else "N/A",
            latency_ms,
            normalized_query,
        )
        return None

    def store_interaction(
        self,
        normalized_query: str,
        generalized_answer: str,
        original_query: str,
        user_id: str,
    ) -> None:
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
            }],
        )
        logger.info("Stored in cache (id=%s, total=%d)", doc_id, self._collection.count())

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
