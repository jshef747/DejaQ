"""RAG admin orchestration — the auth + catalog + vector glue.

Mirrors `admin_service`: functions open a `get_session()`, resolve the workspace,
then coordinate three things per document:
  1. extract text (`rag_ingest`),
  2. record a catalog row (`rag_document_repo` / SQLite),
  3. embed + store chunks in the workspace's RAG collection (`rag_service`).

Deleting a document must undo (3) and (2) together; adding a document that already
exists (same normalised text → same sha) REPLACES it rather than erroring on the
(workspace_id, sha) unique constraint.

Adding is split into two phases because (3) is slow (BGE embeds one chunk at a
time) and used to run synchronously inside the HTTP request - a large upload
held the request open for minutes with no way to tell it apart from a hang.
`begin_ingest` (and the `begin_text`/`begin_upload`/`begin_url` convenience
wrappers) does the fast part - extract, chunk, write a "processing" catalog
row with a known chunk total - and returns immediately. `_embed_and_index`
does the slow part and can be run inline (the `add_text`/`add_upload`/`add_url`
synchronous wrappers below, used by the CLI) or handed to a background job
(`run_ingest`, used by the HTTP router - see routers/admin/rag_documents.py).
"""
from __future__ import annotations

import logging

from app.config import RAG_ENABLED
from app.db import rag_document_repo
from app.db.models.workspace import Workspace
from app.db.session import get_session
from app.schemas.admin.rag_documents import RagDocumentItem
from app.services import rag_ingest, rag_service
from app.services.admin_service import WorkspaceNotFound

logger = logging.getLogger("dejaq.rag")


class RagDocumentNotFound(Exception):
    def __init__(self, doc_id: int) -> None:
        self.doc_id = doc_id
        super().__init__(f"RAG document id={doc_id} not found.")


class RagIngestError(Exception):
    """Extraction produced no usable text — carries a human-readable reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class RagDisabledError(Exception):
    """DEJAQ_RAG_ENABLED is off, so no document may be added."""

    def __init__(self) -> None:
        super().__init__("RAG is disabled on this server (DEJAQ_RAG_ENABLED=false).")


def _resolve_workspace(session, workspace_slug: str) -> Workspace:
    workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
    if workspace is None:
        raise WorkspaceNotFound(workspace_slug)
    return workspace


def _assert_can_add(workspace_slug: str) -> None:
    """Check RAG is on and the workspace exists.

    Runs BEFORE ingest, because ingestion does real work (fetch a URL, OCR an
    image): a request naming a workspace that does not exist must not be able to
    make the server fetch a URL on its behalf, and a server with RAG switched off
    must not accumulate knowledge that retrieval will never read.

    This is the single boundary every add path routes through — the HTTP router
    and the `dejaq-admin rag` CLI both land here — so the kill switch cannot be
    bypassed by reaching the service directly. Reading and deleting stay open
    when the switch is off, so an operator can still inspect and clean up.
    """
    if not RAG_ENABLED:
        raise RagDisabledError()
    with get_session() as session:
        _resolve_workspace(session, workspace_slug)


def list_documents(workspace_slug: str) -> list[RagDocumentItem]:
    with get_session() as session:
        workspace = _resolve_workspace(session, workspace_slug)
        rows = rag_document_repo.list_for_workspace(session, workspace.id)
        return [RagDocumentItem.model_validate(row) for row in rows]


def begin_ingest(
    workspace_slug: str,
    ingest: rag_ingest.IngestResult,
) -> tuple[RagDocumentItem, list[str]]:
    """Fast phase, common to every add_*: validate, dedupe-by-sha, chunk, write
    a "processing" catalog row. Chunking is pure Python (no model call) so it
    costs nothing to do up front - it is what lets the row report a real
    `progress_total` from the moment it exists, instead of an unknown one.

    Returns the row plus its chunks; the caller runs `_embed_and_index` (now,
    inline, or later via `run_ingest`) to do the slow part.
    """
    if not ingest.ok:
        raise RagIngestError(ingest.reason or "could not extract text")
    chunks = rag_service.chunk_text(ingest.text)
    if not chunks:
        raise RagIngestError("document produced no chunks")

    with get_session() as session:
        workspace = _resolve_workspace(session, workspace_slug)
        # Re-adding the same content (same sha) is a replace, not a duplicate,
        # and it updates the existing row IN PLACE. Deleting the row and
        # inserting a new one would satisfy the unique (workspace_id, sha) just
        # as well, but SQLite hands a plain INTEGER PRIMARY KEY the rowid of the
        # row just deleted, so the "new" document can be handed the id whose
        # chunks are about to be cleaned up — and the cleanup would take the
        # chunks it had just written. One id per sha removes that whole class.
        existing = rag_document_repo.get_by_sha(session, workspace.id, ingest.sha)
        if existing is not None:
            row = rag_document_repo.start_processing_existing(
                session,
                existing,
                title=ingest.title,
                kind=ingest.kind,
                source=ingest.source,
                source_ref=ingest.source_ref,
                char_count=ingest.char_count,
                byte_size=ingest.byte_size,
                progress_total=len(chunks),
            )
        else:
            row = rag_document_repo.start_processing_new(
                session,
                workspace.id,
                title=ingest.title,
                kind=ingest.kind,
                source=ingest.source,
                source_ref=ingest.source_ref,
                sha=ingest.sha,
                char_count=ingest.char_count,
                byte_size=ingest.byte_size,
                progress_total=len(chunks),
            )
        item = RagDocumentItem.model_validate(row)
    return item, chunks


def _embed_and_index(
    workspace_slug: str,
    doc_id: int,
    chunks: list[str],
) -> RagDocumentItem | None:
    """Slow phase: embed chunks (reporting progress as it goes) and index them.

    On any failure the row is marked "failed" with the reason and the
    exception is RE-RAISED - a synchronous caller (the CLI, or `add_text` and
    friends below) sees it exactly as it always has. `run_ingest` is the
    fire-and-forget wrapper for a background job; it does not re-raise.

    Returns None if the row was deleted mid-flight (nothing left to finish).
    """
    namespace = rag_service.rag_namespace(workspace_slug)
    total = len(chunks)
    step = max(1, total // 50)  # ~50 progress writes over the run, not one per chunk

    def on_progress(done: int) -> None:
        if done != total and done % step:
            return
        with get_session() as session:
            workspace = _resolve_workspace(session, workspace_slug)
            row = rag_document_repo.get(session, workspace.id, doc_id)
            if row is not None and row.status == "processing":
                rag_document_repo.update_progress(session, row, current=done)

    try:
        # Embedding is the slow part (BGE, in-process, one pass per chunk) and
        # needs no DB row held open, so it runs BEFORE the session below opens.
        # SQLite serialises writers, and a large document embedded inside the
        # transaction would hold the write lock for seconds and fail every
        # concurrent admin write with "database is locked".
        embeddings = rag_service.embed_chunks(chunks, on_progress=on_progress)

        with get_session() as session:
            workspace = _resolve_workspace(session, workspace_slug)
            row = rag_document_repo.get(session, workspace.id, doc_id)
            if row is None:
                logger.info(
                    "rag_ingest_abandoned workspace=%s doc_id=%s reason=deleted",
                    workspace_slug, doc_id,
                )
                return None
            previous_chunk_count = row.chunk_count
            # Index into Chroma while still inside the session, so a Chroma
            # failure rolls back the catalog row (get_session rolls back on
            # exception) - the except block below then records it separately.
            rag_service.index_document(
                namespace,
                row.id,
                chunks,
                embeddings=embeddings,
                workspace_slug=workspace_slug,
                title=row.title,
                kind=row.kind,
                source_ref=row.source_ref,
            )
            # Deterministic chunk ids mean the upsert above already replaced
            # indices 0..len(chunks)-1; only a tail left over from a longer
            # previous version needs removing, and only after the new chunks
            # are safely written.
            if previous_chunk_count > len(chunks):
                rag_service.delete_chunk_tail(namespace, row.id, len(chunks))
            row = rag_document_repo.finish_ready(session, row, chunk_count=len(chunks))
            item = RagDocumentItem.model_validate(row)
        logger.info(
            "rag_add workspace=%s doc_id=%s kind=%s source=%s chunks=%d",
            workspace_slug, item.id, item.kind, item.source, item.chunk_count,
        )
        return item
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        try:
            with get_session() as session:
                workspace = _resolve_workspace(session, workspace_slug)
                row = rag_document_repo.get(session, workspace.id, doc_id)
                if row is not None:
                    rag_document_repo.finish_failed(session, row, reason=reason[:500])
        except Exception:
            logger.error(
                "rag_ingest could not record failure workspace=%s doc_id=%s",
                workspace_slug, doc_id, exc_info=True,
            )
        raise


def run_ingest(workspace_slug: str, doc_id: int, chunks: list[str]) -> RagDocumentItem | None:
    """Background-job entry point for the slow phase - never raises.

    This is what the Celery task and the no-Celery BackgroundTasks fallback
    both call (see routers/admin/rag_documents.py): a background job has
    nothing to propagate a raised exception TO, so the failure is recorded on
    the row (inside `_embed_and_index`) and swallowed here instead.
    """
    try:
        return _embed_and_index(workspace_slug, doc_id, chunks)
    except Exception:
        logger.exception("rag_ingest_failed workspace=%s doc_id=%s", workspace_slug, doc_id)
        return None


def begin_text(workspace_slug: str, title: str, content: str) -> tuple[RagDocumentItem, list[str]]:
    _assert_can_add(workspace_slug)
    return begin_ingest(workspace_slug, rag_ingest.from_text(title, content))


def begin_upload(
    workspace_slug: str,
    filename: str | None,
    data: bytes,
    mime: str | None,
    title: str | None = None,
) -> tuple[RagDocumentItem, list[str]]:
    _assert_can_add(workspace_slug)
    return begin_ingest(workspace_slug, rag_ingest.from_upload(filename, data, mime, title))


def begin_url(workspace_slug: str, url: str, title: str | None = None) -> tuple[RagDocumentItem, list[str]]:
    _assert_can_add(workspace_slug)
    return begin_ingest(workspace_slug, rag_ingest.from_url(url, title))


def add_text(workspace_slug: str, title: str, content: str) -> RagDocumentItem:
    """Synchronous full path (extract → chunk → embed → index), blocking until
    done. Used by the CLI, which has no polling loop of its own.
    """
    item, chunks = begin_text(workspace_slug, title, content)
    return _embed_and_index(workspace_slug, item.id, chunks)


def add_upload(
    workspace_slug: str,
    filename: str | None,
    data: bytes,
    mime: str | None,
    title: str | None = None,
) -> RagDocumentItem:
    """Synchronous full path - see `add_text`."""
    item, chunks = begin_upload(workspace_slug, filename, data, mime, title)
    return _embed_and_index(workspace_slug, item.id, chunks)


def add_url(workspace_slug: str, url: str, title: str | None = None) -> RagDocumentItem:
    """Synchronous full path - see `add_text`."""
    item, chunks = begin_url(workspace_slug, url, title)
    return _embed_and_index(workspace_slug, item.id, chunks)


def _purge_grounded_cache_entries(workspace_slug: str, doc_id: int) -> int:
    """Delete cache entries grounded in this document, across every department.

    This codebase has no in-place document edit (see the module docstring):
    correcting a document means deleting the wrong version and adding the
    corrected text as a new document (a new id). So a delete is the one place
    that reliably marks a document's content as no longer current, and the
    place a stale grounded cache answer must stop being served from. Only
    entries carrying THIS doc's id in their `rag_document_ids` provenance are
    removed - every other cache entry, including ones from other documents or
    the ordinary Q&A cache, is untouched. Entries stored before this fix
    shipped carry no provenance and cannot be identified this way; they age
    out through the existing score-eviction floor instead.

    RAG knowledge is shared across a workspace's departments (one
    "{workspace}__rag_kb" collection, not per-department), but each
    department has its OWN Q&A cache namespace, so every one of them needs
    sweeping - same fan-out `dejaq-admin cache purge-images` uses.
    """
    from app.services import admin_service
    from app.services.memory_chromaDB import get_memory_service

    try:
        departments = admin_service.list_departments(workspace_slug=workspace_slug)
    except WorkspaceNotFound:
        return 0
    namespaces = {d.cache_namespace for d in departments}
    # Requests with no X-DejaQ-Department header land here regardless of
    # whether any department exists (app/middleware/api_key.py).
    namespaces.add(f"{workspace_slug}--default")

    deleted = 0
    for namespace in namespaces:
        try:
            deleted += get_memory_service(namespace).purge_grounded_entries(doc_id)
        except Exception:
            logger.warning(
                "RAG-grounded cache purge failed for namespace=%s doc_id=%s",
                namespace, doc_id, exc_info=True,
            )
    return deleted


def delete_document(
    workspace_slug: str,
    doc_id: int,
) -> bool:
    namespace = rag_service.rag_namespace(workspace_slug)
    with get_session() as session:
        workspace = _resolve_workspace(session, workspace_slug)
        row = rag_document_repo.get(session, workspace.id, doc_id)
        if row is None:
            raise RagDocumentNotFound(doc_id)
        rag_service.delete_document_chunks(namespace, doc_id)
        rag_document_repo.delete(session, workspace.id, doc_id)
    purged = _purge_grounded_cache_entries(workspace_slug, doc_id)
    logger.info(
        "rag_delete workspace=%s doc_id=%s purged_cache_entries=%d",
        workspace_slug, doc_id, purged,
    )
    return True
