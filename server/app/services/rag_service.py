"""Rug (RAG) — the vector side of the per-workspace knowledge layer.

This module owns everything that touches ChromaDB for RAG: turning a document's
text into chunks, embedding + storing those chunks, retrieving them for a query,
and deleting them. It has NO knowledge of HTTP, auth, or the SQLite catalog —
that orchestration lives in `rag_admin_service`.

Design notes:
- RAG chunks live in their OWN Chroma collection per workspace,
  "{workspace_slug}__rag_kb", kept apart from the Q→A cache collections
  ("{workspace_slug}__{dept}"). The cache is volatile — score-evicted and
  deleted on a thumbs-down — and curated knowledge must never be wiped that way.
  The "__rag_kb" suffix is load-bearing: the eviction beat task skips it.
- Chunks are embedded with the SAME BGE model the cache uses
  (`memory_chromaDB.embed_text`), so retrieval distances are comparable to cache
  distances and there is one embedder loaded in-process, not two.
- A chunk's id is deterministic ("{rag_document_id}:{index}") so re-indexing a
  document upserts over its old chunks instead of duplicating them.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import chromadb

from app.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    RAG_CHUNK_CHARS,
    RAG_CHUNK_OVERLAP,
)
from app.services.memory_chromaDB import embed_text

logger = logging.getLogger("dejaq.rag")

# Suffix that marks a collection as a RAG knowledge base rather than a Q→A cache.
# The eviction beat task (tasks/cache_tasks.py) keys off this to leave RAG alone.
#
# The internal underscore in "rag_kb" is load-bearing, not cosmetic: department
# cache collections are named "{workspace_slug}__{dept_slug}" and `dept_slug`
# comes from slugify_name(), which maps every non-[a-z0-9] character (including
# `_`) to `-`. So a department slug can NEVER contain an underscore — which means
# no department namespace can ever equal "{workspace_slug}__rag_kb". A plain
# "__rag" suffix WOULD collide with a department literally named "RAG"
# (slug "rag" → namespace "{ws}__rag"), which would merge that department's Q→A
# cache into the knowledge base and make the eviction guard skip it.
RAG_NAMESPACE_SUFFIX = "__rag_kb"


def rag_namespace(workspace_slug: str) -> str:
    """The single source of truth for a workspace's RAG collection name."""
    return f"{workspace_slug}{RAG_NAMESPACE_SUFFIX}"


def is_rag_namespace(namespace: str) -> bool:
    return namespace.endswith(RAG_NAMESPACE_SUFFIX)


@dataclass(frozen=True)
class RagChunk:
    text: str
    title: str
    distance: float
    rag_document_id: int
    chunk_index: int


# --- Chroma collection pool (mirrors memory_chromaDB.get_memory_service) -------

_pool: dict[str, "chromadb.api.models.Collection.Collection"] = {}


def get_rag_collection(namespace: str):
    """Return a cached Chroma collection for a RAG namespace, creating it lazily.

    No embedding_function is registered — we embed manually and pass vectors in,
    exactly like MemoryService, to avoid persisted-embedding-function conflicts.
    """
    if namespace not in _pool:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        _pool[namespace] = client.get_or_create_collection(
            name=namespace,
            metadata={"hnsw:space": "cosine"},
        )
    return _pool[namespace]


# --- Chunking -----------------------------------------------------------------

def chunk_text(text: str) -> list[str]:
    """Split text into overlapping windows of ~RAG_CHUNK_CHARS characters.

    Prefers to break on a paragraph or sentence boundary near the window edge so
    a chunk does not end mid-sentence; falls back to a hard character cut when no
    boundary is close. Overlap (RAG_CHUNK_OVERLAP) carries a little context from
    the previous chunk so a fact that straddles a boundary is still retrievable.
    """
    text = text.strip()
    if not text:
        return []
    size = max(1, RAG_CHUNK_CHARS)
    overlap = max(0, min(RAG_CHUNK_OVERLAP, size - 1))
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # Look for a clean break in the last ~20% of the window.
            window = text[start:end]
            floor = int(size * 0.8)
            cut = -1
            for sep in ("\n\n", "\n", ". ", "? ", "! ", " "):
                idx = window.rfind(sep)
                if idx >= floor:
                    cut = idx + len(sep)
                    break
            if cut != -1:
                end = start + cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


# --- Indexing / retrieval / deletion ------------------------------------------

def index_document(
    namespace: str,
    rag_document_id: int,
    chunks: list[str],
    *,
    workspace_slug: str,
    title: str,
    kind: str,
    source_ref: str | None,
) -> int:
    """Embed and upsert a document's chunks. Returns the number of chunks stored.

    Ids are deterministic ("{doc_id}:{i}"), so calling this again for the same
    document replaces its chunks in place. Callers that re-index an already-seen
    document should delete_document_chunks first to clear a now-shorter tail.
    """
    if not chunks:
        return 0
    collection = get_rag_collection(namespace)
    ids = [f"{rag_document_id}:{i}" for i in range(len(chunks))]
    embeddings = [embed_text(c) for c in chunks]
    stored_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    metadatas = [
        {
            "rag_document_id": rag_document_id,
            "workspace_slug": workspace_slug,
            "title": title,
            "kind": kind,
            "source_ref": source_ref or "",
            "chunk_index": i,
            "stored_at": stored_at,
        }
        for i in range(len(chunks))
    ]
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )
    logger.info(
        "rag_index namespace=%s doc_id=%s chunks=%d title=%r",
        namespace, rag_document_id, len(chunks), title[:60],
    )
    return len(chunks)


def retrieve(
    namespace: str,
    query: str,
    top_k: int,
    max_distance: float,
) -> list[RagChunk]:
    """Return the closest RAG chunks to `query`, filtered by cosine distance.

    Returns [] when the collection is empty or nothing clears max_distance — the
    caller then answers exactly as it does today, without grounding.
    """
    collection = get_rag_collection(namespace)
    count = collection.count()
    if count == 0:
        return []
    n = min(max(1, top_k), count)
    results = collection.query(
        query_embeddings=[embed_text(query)],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )
    if not (results["ids"] and results["ids"][0]):
        return []

    out: list[RagChunk] = []
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results["distances"] else []
    for i in range(len(results["ids"][0])):
        dist = float(dists[i]) if i < len(dists) else 1.0
        if dist > max_distance:
            continue
        meta = metas[i] if i < len(metas) else {}
        text = (docs[i] if i < len(docs) else "") or ""
        if not text.strip():
            continue
        out.append(
            RagChunk(
                text=text,
                title=str(meta.get("title", "")),
                distance=dist,
                rag_document_id=int(meta.get("rag_document_id", 0)),
                chunk_index=int(meta.get("chunk_index", i)),
            )
        )
    return out


def delete_document_chunks(namespace: str, rag_document_id: int) -> None:
    """Remove every chunk belonging to one document.

    Raises on a Chroma failure: callers delete the catalog row only after this
    succeeds, so a failed vector delete fails the request instead of leaving
    orphaned chunks that keep grounding answers with no admin handle left to
    remove them.
    """
    collection = get_rag_collection(namespace)
    collection.delete(where={"rag_document_id": rag_document_id})
    logger.info("rag_delete_chunks namespace=%s doc_id=%s", namespace, rag_document_id)


def delete_namespace(namespace: str) -> None:
    """Drop a workspace's entire RAG collection (used on workspace deletion)."""
    logger_ = logging.getLogger("dejaq.rag")
    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        existing = [c.name for c in client.list_collections()]
        if namespace in existing:
            client.delete_collection(namespace)
            logger_.info("Deleted RAG collection '%s'", namespace)
        _pool.pop(namespace, None)
    except Exception:
        logger_.warning("Could not delete RAG collection '%s'", namespace, exc_info=True)
