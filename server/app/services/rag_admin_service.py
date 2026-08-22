"""RAG admin orchestration — the auth + catalog + vector glue.

Mirrors `admin_service`: functions open a `get_session()`, resolve the workspace,
then coordinate three things per document:
  1. extract text (`rag_ingest`),
  2. record a catalog row (`rag_document_repo` / SQLite),
  3. embed + store chunks in the workspace's RAG collection (`rag_service`).

Deleting a document must undo (3) and (2) together; adding a document that already
exists (same normalised text → same sha) REPLACES it rather than erroring on the
(workspace_id, sha) unique constraint.
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


def _store(
    workspace_slug: str,
    ingest: rag_ingest.IngestResult,
) -> RagDocumentItem:
    """Common tail for every add_*: validate, dedupe-by-sha, catalog + index."""
    if not ingest.ok:
        raise RagIngestError(ingest.reason or "could not extract text")

    namespace = rag_service.rag_namespace(workspace_slug)
    chunks = rag_service.chunk_text(ingest.text)
    if not chunks:
        raise RagIngestError("document produced no chunks")
    # Embedding is the slow part (BGE, in-process, one pass per chunk) and needs
    # no DB row, so it runs BEFORE the session opens. SQLite serialises writers,
    # and a large document embedded inside the transaction would hold the write
    # lock for seconds and fail every concurrent admin write with "database is
    # locked".
    embeddings = rag_service.embed_chunks(chunks)

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
        previous_chunk_count = existing.chunk_count if existing is not None else 0
        if existing is not None:
            row = rag_document_repo.update_content(
                session,
                existing,
                title=ingest.title,
                kind=ingest.kind,
                source=ingest.source,
                source_ref=ingest.source_ref,
                char_count=ingest.char_count,
                chunk_count=len(chunks),
            )
        else:
            row = rag_document_repo.create(
                session,
                workspace.id,
                title=ingest.title,
                kind=ingest.kind,
                source=ingest.source,
                source_ref=ingest.source_ref,
                sha=ingest.sha,
                char_count=ingest.char_count,
                chunk_count=len(chunks),
            )
        # Index into Chroma while still inside the session, so a Chroma failure
        # rolls back the catalog row (get_session rolls back on exception).
        rag_service.index_document(
            namespace,
            row.id,
            chunks,
            embeddings=embeddings,
            workspace_slug=workspace_slug,
            title=ingest.title,
            kind=ingest.kind,
            source_ref=ingest.source_ref,
        )
        # Deterministic chunk ids mean the upsert above already replaced indices
        # 0..len(chunks)-1; only a tail left over from a longer previous version
        # needs removing, and only after the new chunks are safely written.
        if previous_chunk_count > len(chunks):
            rag_service.delete_chunk_tail(namespace, row.id, len(chunks))
        item = RagDocumentItem.model_validate(row)
    logger.info(
        "rag_add workspace=%s doc_id=%s kind=%s source=%s chunks=%d",
        workspace_slug, item.id, item.kind, item.source, item.chunk_count,
    )
    return item


def add_text(
    workspace_slug: str,
    title: str,
    content: str,
) -> RagDocumentItem:
    _assert_can_add(workspace_slug)
    return _store(workspace_slug, rag_ingest.from_text(title, content))


def add_upload(
    workspace_slug: str,
    filename: str | None,
    data: bytes,
    mime: str | None,
    title: str | None = None,
) -> RagDocumentItem:
    _assert_can_add(workspace_slug)
    return _store(workspace_slug, rag_ingest.from_upload(filename, data, mime, title))


def add_url(
    workspace_slug: str,
    url: str,
    title: str | None = None,
) -> RagDocumentItem:
    _assert_can_add(workspace_slug)
    return _store(workspace_slug, rag_ingest.from_url(url, title))


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
    logger.info("rag_delete workspace=%s doc_id=%s", workspace_slug, doc_id)
    return True
