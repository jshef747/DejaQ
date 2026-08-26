"""RAG — the vector side of the per-workspace knowledge layer.

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
- Chunks are embedded with the SAME text embedder the cache uses
  (`memory_chromaDB.embed_text`, model configured via `TEXT_EMBEDDING_MODEL`),
  so retrieval distances are comparable to cache distances and there is one
  embedder loaded in-process, not two.
- A chunk's id is deterministic ("{rag_document_id}:{index}") so re-indexing a
  document upserts over its old chunks instead of duplicating them.
"""
from __future__ import annotations

import ast
import logging
import time
from dataclasses import dataclass
from typing import Callable

import chromadb
import numpy as np

from app.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    RAG_CHUNK_CHARS,
    RAG_CHUNK_OVERLAP,
    RAG_EXHAUSTIVE_MAX_CHUNKS,
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

# Chroma rejects an upsert whose row count exceeds a server-side ceiling
# derived from SQLite's bound-parameter limit (measured 5,461 on a local
# install) - one request over it fails outright, not partially. A 4,100-chunk
# document stayed under that by luck; a 5,722-chunk one (measured live,
# fm/dejaq-kb-upload-progress) did not, and the whole upsert was rejected with
# "Batch size N exceeds maximum batch size 5461" after minutes of embedding.
# This constant is deliberately far below any observed minimum so ingestion
# never has to probe the server's actual limit - it just slices the upsert
# into requests that always fit.
_MAX_UPSERT_BATCH = 1000


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


# --- Code-aware chunking (Python) ---------------------------------------------
#
# `chunk_text` above splits on prose boundaries - paragraphs, then sentences,
# then any space. On source code that reliably cuts through the middle of a
# function: measured on psf/requests, `super_len` (2,688 chars, over the
# RAG_CHUNK_CHARS budget on its own) spread across four chunks whose first one
# opened with the tail of the PREVIOUS function, and the chunk holding the
# `return` line was never retrieved for a question about what it returns.
#
# The fix is to cut on the file's own structure instead. Python needs no new
# dependency for that: `ast` gives an exact line span for every statement,
# including decorators, so a function or class can be kept whole and an
# oversized one can be split at its own inner statement boundaries rather than
# mid-expression. Only Python gets this - `_PYTHON_SUFFIXES` is the whole
# language test, and every other file (Markdown, JS, JSON, YAML, plain text)
# falls through to `chunk_text` untouched. A tree-sitter dependency would buy
# the other languages, and nothing in the measured battery justifies it yet.

_PYTHON_SUFFIXES = (".py", ".pyi")


def _is_python_source(source_ref: str | None) -> bool:
    """True when a document's origin names a Python file.

    `source_ref` is a GitHub blob URL for a repo import and the uploaded
    filename for an upload; a pasted document has none and is never code.
    A query string or fragment is stripped first so a URL still resolves.
    """
    if not source_ref:
        return False
    path = source_ref.split("?", 1)[0].split("#", 1)[0]
    return path.lower().endswith(_PYTHON_SUFFIXES)


def _child_statements(node) -> list:
    """Every statement directly inside `node`, in source order.

    Walks the node's own children rather than `node.body` so a `try` keeps its
    handlers and an `if` keeps its `else` - both live outside `.body` and
    would otherwise be dropped from the split.
    """
    kids = [
        child
        for child in ast.iter_child_nodes(node)
        if isinstance(child, (ast.stmt, ast.excepthandler))
    ]
    kids.sort(key=lambda c: (c.lineno, c.col_offset))
    return kids


def _statement_start(node) -> int:
    """First line of a statement, counting its decorators.

    `node.lineno` points at the `def`/`class` keyword, so a decorated function
    would otherwise lose its decorators to the preceding chunk.
    """
    decorators = getattr(node, "decorator_list", None) or []
    return min([d.lineno for d in decorators] + [node.lineno])


def _tile(statements: list, first_line: int, last_line: int) -> list[tuple[int, int, object]]:
    """Cover [first_line, last_line] with one span per statement, no gaps.

    Spans are stretched to touch rather than tracking each statement's exact
    extent, because `ast` cannot see comments or blank lines: slicing a
    statement's own line span alone would silently drop every comment between
    two functions from the document. Tiling keeps the file whole - concatenate
    the spans and you get the source back.
    """
    spans: list[tuple[int, int, object]] = []
    cursor = first_line
    for i, stmt in enumerate(statements):
        end = last_line if i == len(statements) - 1 else stmt.end_lineno
        spans.append((cursor, max(end, cursor), stmt))
        cursor = max(end, cursor) + 1
    return spans


def _span_text(lines: list[str], first_line: int, last_line: int) -> str:
    return "\n".join(lines[first_line - 1:last_line])


def _clean(chunk: str) -> str:
    """Trim blank edges without touching the first line's indentation.

    A plain `.strip()` would eat the leading spaces that say which block a
    fragment of a method body came from.
    """
    return chunk.strip("\n").rstrip()


def _peel_oversized_leads(
    spans: list[tuple[int, int, object]],
    lines: list[str],
    header: str,
    budget: int,
) -> list[tuple[int, int, object]]:
    """Split "leading comments + statement" spans that only overflow together."""
    out: list[tuple[int, int, object]] = []
    for first_line, last_line, node in spans:
        start = _statement_start(node) if node is not None else first_line
        if (
            start > first_line
            and _header_cost(header) + len(_span_text(lines, first_line, last_line)) > budget
            and _header_cost(header) + len(_span_text(lines, start, last_line)) <= budget
        ):
            out.append((first_line, start - 1, None))
            out.append((start, last_line, node))
        else:
            out.append((first_line, last_line, node))
    return out


def _header_cost(header: str) -> int:
    """Worst-case rendered size of a breadcrumb, for budget arithmetic."""
    return len(_breadcrumb_comment(header, ""))


def _breadcrumb_comment(header: str, body: str) -> str:
    """Render the enclosing declarations as a COMMENT above a fragment.

    Written as comments rather than as the declaration lines themselves for a
    measured reason: repeating `def super_len(o: Any) -> int:` verbatim on four
    fragments of one function made the answering model report "several
    different implementations of super_len" and hedge, even though it had the
    right line in front of it. Commented out, the same identifiers are still
    there for the embedder and for the reader, and nothing looks like a second
    definition.

    The innermost line is dropped when the fragment already contains the
    declaration itself - the first piece of a split needs no "fragment of"
    banner - while the outer chain (the class a method sits in) still applies.
    """
    lines = [line for line in header.split("\n") if line.strip()]
    if lines and lines[-1] in body:
        lines = lines[:-1]
    if not lines:
        return ""
    return "# fragment of:\n" + "\n".join(f"# {line}" for line in lines) + "\n"


def _pack(
    spans: list[tuple[int, int, object]],
    lines: list[str],
    header: str,
    budget: int,
    out: list[str],
) -> None:
    """Fill chunks with whole statements, splitting only what cannot fit.

    `header` is a breadcrumb of the enclosing declaration lines - "class
    Session:" then "    def request(" - carried onto every chunk carved out of
    one over-budget unit, so a fragment of a long method still names the method
    and the class it sits in. Without it the tail of a split function mentions
    that function nowhere, and a question naming it cannot match the piece that
    answers it - which is the measured `super_len` failure.
    """
    # A comment block sitting above a function belongs with it - that is why
    # `_tile` stretches the span back over it - but only while the pair still
    # fits. When it does not and the function alone would, the comment is peeled
    # off into its own span instead, so an unrelated note above a function does
    # not get the function split (measured: DejaQ's `image_fingerprint.dhash`,
    # 555 chars, split by a 460-char rejected-design comment above it).
    spans = _peel_oversized_leads(spans, lines, header, budget)
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        body = "\n".join(current)
        lead = _breadcrumb_comment(header, body)
        chunk = _clean(lead + body)
        if chunk:
            out.append(chunk)
        current.clear()

    for first_line, last_line, node in spans:
        text = _span_text(lines, first_line, last_line)
        if not text.strip():
            continue
        if _header_cost(header) + len(text) > budget:
            flush()
            _split(node, first_line, last_line, lines, header, budget, out)
            continue
        used = _header_cost(header) + sum(len(part) + 1 for part in current)
        if current and used + len(text) > budget:
            flush()
        current.append(text)
    flush()


def _declaration_line(node, lines: list[str]) -> str:
    """The node's own `def`/`class`/`if` line, for use as a breadcrumb.

    One line, taken verbatim - never the whole signature. A long signature can
    run to dozens of lines, and repeating it on every chunk of a long method
    would spend the budget on punctuation.
    """
    if node is None:
        return ""
    return lines[node.lineno - 1].rstrip()


def _split(
    node,
    first_line: int,
    last_line: int,
    lines: list[str],
    header: str,
    budget: int,
    out: list[str],
) -> None:
    """Break one over-budget statement at the boundaries inside it.

    The decorators and signature become the first span in their own right, so
    nothing is dropped and no outer-scope line ends up filed under an inner
    scope's breadcrumb. Each level down is strictly smaller than the one above,
    so this terminates.
    A statement that still does not fit and has nothing inside it - a
    2,000-character dict literal - is the one case with no structural boundary
    left, and only that case falls back to the prose splitter.
    """
    children = _child_statements(node) if node is not None else []
    if children:
        body_start = _statement_start(children[0])
        spans = _tile(children, max(body_start, first_line), last_line)
        if body_start > first_line:
            # Decorators and the signature are content in their own right, and
            # they belong to THIS node - not to whatever the recursion below
            # descends into. Stretching the first child back over them would
            # put an outer scope's lines under an inner scope's breadcrumb.
            spans.insert(0, (first_line, body_start - 1, None))
        breadcrumb = _declaration_line(node, lines)
        sub_header = f"{header}{breadcrumb}\n" if breadcrumb.strip() else header
        # Keep the innermost few levels; a deep nest would otherwise spend the
        # whole budget on breadcrumbs.
        crumbs = sub_header.split("\n")
        if len(crumbs) > 4:
            sub_header = "\n".join(crumbs[-4:])
        _pack(spans, lines, sub_header, budget, out)
        return
    out.extend(
        _clean(_breadcrumb_comment(header, part) + part)
        for part in chunk_text(_span_text(lines, first_line, last_line))
    )


def _merge_adjacent(chunks: list[str], budget: int) -> list[str]:
    """Glue neighbouring chunks back together while they still fit the budget.

    Splitting is depth-first, so it leaves small offcuts behind: the piece
    before an over-budget sibling gets flushed early, and the tail of a split
    is whatever was left. Measured on `super_len`, that produced seven pieces,
    two of them under 120 characters and carrying little but their breadcrumb -
    a chunk that short wins a top-k slot without answering anything. Chunks are
    emitted in source order, so merging neighbours only ever restores text that
    was adjacent in the file.
    """
    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) + 1 + len(chunk) <= budget:
            merged[-1] = f"{merged[-1]}\n{chunk}"
        else:
            merged.append(chunk)
    return merged


def chunk_python(text: str) -> list[str] | None:
    """Chunk Python source on its own structure, or None if it will not parse.

    None (not an exception, not a partial result) is the signal to fall back to
    `chunk_text`: a file with a syntax error, or written for a newer Python
    than this interpreter, still belongs in the knowledge base - just chunked
    as prose, exactly as it was before this existed.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    lines = text.splitlines()
    if not lines:
        return []
    budget = max(1, RAG_CHUNK_CHARS)
    out: list[str] = []
    _pack(
        _tile(tree.body, 1, len(lines)) if tree.body else [(1, len(lines), None)],
        lines, "", budget, out,
    )
    return _merge_adjacent(out, budget)


def chunk_document(text: str, source_ref: str | None = None) -> list[str]:
    """The one entry point ingestion uses: code-aware for Python, prose otherwise.

    Deliberately not a registry or a policy layer - one `if`, because one
    language is what the measurement covers. Chunking stays a pure function of
    (text, source_ref), which is what keeps a re-import of an unchanged file
    byte-identical to the last one.
    """
    if _is_python_source(source_ref):
        chunks = chunk_python(text)
        if chunks is not None:
            return [c for c in chunks if c.strip()]
    return chunk_text(text)


# --- Indexing / retrieval / deletion ------------------------------------------

def embed_chunks(
    chunks: list[str], on_progress: Callable[[int], None] | None = None
) -> list[list[float]]:
    """Embed chunks with the shared BGE model, one at a time.

    Split out from index_document so a caller can pay this cost outside a DB
    transaction — it is the slow part of ingestion and holds no locks of its own.
    `on_progress`, when given, is called with the count embedded so far after
    every chunk. This is the only phase of ingestion whose cost scales with the
    document's size, so it is the only honest unit of progress to report.
    """
    out: list[list[float]] = []
    for i, chunk in enumerate(chunks, start=1):
        out.append(embed_text(chunk))
        if on_progress is not None:
            on_progress(i)
    return out


def index_document(
    namespace: str,
    rag_document_id: int,
    chunks: list[str],
    *,
    workspace_slug: str,
    title: str,
    kind: str,
    source_ref: str | None,
    embeddings: list[list[float]] | None = None,
) -> int:
    """Embed and upsert a document's chunks. Returns the number of chunks stored.

    Ids are deterministic ("{doc_id}:{i}"), so calling this again for the same
    document replaces its chunks in place. A re-index that produced FEWER chunks
    than last time leaves the old tail behind: clear it with `delete_chunk_tail`
    AFTER this call, never with `delete_document_chunks` before it — deleting
    first would drop chunks with nothing written yet if the index then failed.
    `embeddings` may carry vectors already computed by `embed_chunks`; they are
    recomputed here when absent or out of step with `chunks`.
    """
    if not chunks:
        return 0
    collection = get_rag_collection(namespace)
    ids = [f"{rag_document_id}:{i}" for i in range(len(chunks))]
    if embeddings is None or len(embeddings) != len(chunks):
        embeddings = embed_chunks(chunks)
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
    for start in range(0, len(ids), _MAX_UPSERT_BATCH):
        end = start + _MAX_UPSERT_BATCH
        collection.upsert(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            documents=chunks[start:end],
            metadatas=metadatas[start:end],
        )
    logger.info(
        "rag_index namespace=%s doc_id=%s chunks=%d title=%r",
        namespace, rag_document_id, len(chunks), title[:60],
    )
    return len(chunks)


def _ann_query(collection, query_embedding: list[float], n: int) -> tuple[list, list, list]:
    """ChromaDB's own HNSW (approximate) search."""
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )
    if not (results["ids"] and results["ids"][0]):
        return [], [], []
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results["distances"] else []
    return docs, metas, dists


def _exhaustive_query(collection, query_embedding: list[float], n: int) -> tuple[list, list, list]:
    """Brute-force linear scan over every chunk in the collection.

    ChromaDB's HNSW index can miss a chunk that is objectively the best
    match: measured on a real knowledge base where one large document's
    chunks dominated the approximate graph, a chunk at cosine distance 0.044
    (a near-perfect match) was never returned even at n_results=2000 of
    5,136 total chunks — see evals/rag_recall/ and docs/rag-layer.md. A
    curated knowledge base is small enough (gated by
    RAG_EXHAUSTIVE_MAX_CHUNKS) that an exact scan is cheap and removes the
    failure mode outright instead of tuning around it.

    `embed_text` L2-normalizes its output, so cosine distance is `1 - dot
    product` — the same metric the collection is created with
    (`"hnsw:space": "cosine"`), just computed exactly instead of approximately.
    """
    got = collection.get(include=["embeddings", "documents", "metadatas"])
    if not got["ids"]:
        return [], [], []
    embeddings = np.asarray(got["embeddings"], dtype=np.float32)
    q = np.asarray(query_embedding, dtype=np.float32)
    distances = 1.0 - (embeddings @ q)
    order = np.argsort(distances)[:n]
    docs = [got["documents"][i] for i in order]
    metas = [got["metadatas"][i] for i in order]
    dists = [float(distances[i]) for i in order]
    return docs, metas, dists


def retrieve(
    namespace: str,
    query: str,
    top_k: int,
    max_distance: float,
) -> list[RagChunk]:
    """Return the closest RAG chunks to `query`, filtered by cosine distance.

    Returns [] when the collection is empty or nothing clears max_distance — the
    caller then answers exactly as it does today, without grounding. Below
    RAG_EXHAUSTIVE_MAX_CHUNKS total chunks, searches exhaustively rather than
    through Chroma's approximate index — see `_exhaustive_query`.
    """
    collection = get_rag_collection(namespace)
    count = collection.count()
    if count == 0:
        return []
    n = min(max(1, top_k), count)
    query_embedding = embed_text(query)
    if count <= RAG_EXHAUSTIVE_MAX_CHUNKS:
        docs, metas, dists = _exhaustive_query(collection, query_embedding, n)
    else:
        docs, metas, dists = _ann_query(collection, query_embedding, n)
    if not docs:
        return []

    out: list[RagChunk] = []
    for i in range(len(docs)):
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


def retrieve_multi(
    namespace: str,
    queries: list[str],
    top_k: int,
    max_distance: float,
) -> list[RagChunk]:
    """Retrieve against several query texts and merge by best distance.

    Used because the context enricher's standalone rewrite of a follow-up can
    drift far enough from the user's original wording to lose a chunk
    retrieval would have found on the raw text (measured in
    evals/rag_recall/measure_enrichment.py). Duplicate/blank query texts are
    only searched once, so this costs nothing extra on a single-turn request
    (enrich() is a no-op without history — same text twice, one search).
    Each (document, chunk) keeps its best distance across every query it
    matched under; the merged results are re-sorted and capped at top_k.
    """
    seen_queries = list(dict.fromkeys(q for q in queries if q))
    if not seen_queries:
        return []
    best: dict[tuple[int, int], RagChunk] = {}
    for query in seen_queries:
        for chunk in retrieve(namespace, query, top_k, max_distance):
            key = (chunk.rag_document_id, chunk.chunk_index)
            existing = best.get(key)
            if existing is None or chunk.distance < existing.distance:
                best[key] = chunk
    return sorted(best.values(), key=lambda c: c.distance)[:top_k]


def retrieve_by_document(
    namespace: str,
    rag_document_id: int,
    query: str,
    top_k: int,
) -> list[RagChunk]:
    """Return the closest chunks to `query` FROM ONE DOCUMENT ONLY.

    Thin wrapper over `retrieve_by_documents` for the one-document case — see
    that function for why an explicit `@`-reference filters by id instead of
    searching.
    """
    return retrieve_by_documents(namespace, [rag_document_id], query, top_k)


def retrieve_by_documents(
    namespace: str,
    rag_document_ids: list[int],
    query: str,
    top_k: int,
) -> list[RagChunk]:
    """Return the closest chunks to `query` FROM A FIXED SET OF DOCUMENTS ONLY.

    For an explicit `@`-reference: the caller already knows which documents it
    wants, so this is a `where={"rag_document_id": {"$in": [...]}}` metadata
    filter, not a nearest-neighbour search over the whole collection. It ranks
    only among those documents' own chunks and therefore cannot be crowded out
    by an unrelated document the way `retrieve()` can (see docs — the measured
    approximate-search recall bug this feature exists to sidestep).

    One id is a single-file reference; many ids are a whole imported repository
    (every row sharing one `group_key`), which is one catalog row per file.
    Ranking WITHIN the set is ordinary vector distance — a repo reference gets
    the same top_k budget a single file does, so a large repo returns its best
    few chunks, not a chunk per file. That is retrieval ranking, deliberately
    left alone here.

    No max_distance gate: the documents are already pinned by id, not by
    distance, so returning the top_k closest chunks regardless of distance is
    correct — unlike `retrieve()`, there is no "wrong document" outcome to
    gate against.

    Returns [] when the collection is empty, the id set is empty, or none of
    the documents have chunks (deleted, or never indexed) — the caller then
    answers ungrounded, exactly as `retrieve()`'s callers do on an empty result.
    """
    if not rag_document_ids:
        return []
    collection = get_rag_collection(namespace)
    if collection.count() == 0:
        return []
    # Chroma rejects a bare scalar under `$in` and a one-element `$in` is the
    # same query as equality, so both forms are spelled out rather than always
    # sending a list.
    ids = sorted(set(rag_document_ids))
    where = (
        {"rag_document_id": ids[0]} if len(ids) == 1
        else {"rag_document_id": {"$in": ids}}
    )
    results = collection.query(
        query_embeddings=[embed_text(query)],
        n_results=max(1, top_k),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    if not (results["ids"] and results["ids"][0]):
        return []

    out: list[RagChunk] = []
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results["distances"] else []
    for i in range(len(results["ids"][0])):
        meta = metas[i] if i < len(metas) else {}
        text = (docs[i] if i < len(docs) else "") or ""
        if not text.strip():
            continue
        out.append(
            RagChunk(
                text=text,
                title=str(meta.get("title", "")),
                distance=float(dists[i]) if i < len(dists) else 1.0,
                rag_document_id=int(meta.get("rag_document_id", ids[0])),
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


def delete_chunk_tail(namespace: str, rag_document_id: int, keep_count: int) -> None:
    """Drop a re-indexed document's chunks beyond its new length.

    Chunk ids are deterministic, so re-indexing upserts over indices
    0..keep_count-1; a shorter rewrite leaves the old tail behind, still
    retrievable and no longer part of the document. Only that tail is removed —
    never the chunks just written.
    """
    collection = get_rag_collection(namespace)
    collection.delete(
        where={
            "$and": [
                {"rag_document_id": {"$eq": rag_document_id}},
                {"chunk_index": {"$gte": keep_count}},
            ]
        }
    )
    logger.info(
        "rag_delete_chunk_tail namespace=%s doc_id=%s from_index=%d",
        namespace, rag_document_id, keep_count,
    )


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
