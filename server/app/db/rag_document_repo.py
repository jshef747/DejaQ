from sqlalchemy.orm import Session

from app.db.models.rag_document import RagDocument


def start_processing_new(
    session: Session,
    workspace_id: int,
    *,
    title: str,
    kind: str,
    source: str,
    source_ref: str | None,
    sha: str,
    char_count: int,
    progress_total: int,
    byte_size: int = 0,
    group_key: str | None = None,
) -> RagDocument:
    """Catalog a brand-new document as ingestion begins.

    chunk_count stays 0 until `finish_ready` - a row in status="processing"
    must never be mistaken for indexed knowledge (see rag_admin_service).
    """
    row = RagDocument(
        workspace_id=workspace_id,
        title=title,
        kind=kind,
        source=source,
        source_ref=source_ref,
        group_key=group_key,
        sha=sha,
        char_count=char_count,
        byte_size=byte_size,
        chunk_count=0,
        status="processing",
        progress_current=0,
        progress_total=progress_total,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def start_processing_existing(
    session: Session,
    row: RagDocument,
    *,
    title: str,
    kind: str,
    source: str,
    source_ref: str | None,
    char_count: int,
    progress_total: int,
    byte_size: int = 0,
    group_key: str | None = None,
) -> RagDocument:
    """Re-ingest an existing document (same sha) in place, keeping its id.

    chunk_count is left untouched until `finish_ready` - the previous version
    keeps grounding answers while the new one embeds.
    """
    row.title = title
    row.kind = kind
    row.source = source
    row.source_ref = source_ref
    row.group_key = group_key
    row.char_count = char_count
    row.byte_size = byte_size
    row.status = "processing"
    row.progress_current = 0
    row.progress_total = progress_total
    row.error_message = None
    session.flush()
    session.refresh(row)
    return row


def update_progress(session: Session, row: RagDocument, *, current: int) -> None:
    row.progress_current = current
    session.flush()


def finish_ready(session: Session, row: RagDocument, *, chunk_count: int) -> RagDocument:
    row.status = "ready"
    row.chunk_count = chunk_count
    row.progress_current = chunk_count
    row.progress_total = chunk_count
    row.error_message = None
    session.flush()
    session.refresh(row)
    return row


def finish_failed(session: Session, row: RagDocument, *, reason: str) -> RagDocument:
    row.status = "failed"
    row.error_message = reason
    session.flush()
    session.refresh(row)
    return row


def get(session: Session, workspace_id: int, doc_id: int) -> RagDocument | None:
    return (
        session.query(RagDocument)
        .filter_by(workspace_id=workspace_id, id=doc_id)
        .first()
    )


def get_by_sha(session: Session, workspace_id: int, sha: str) -> RagDocument | None:
    return (
        session.query(RagDocument)
        .filter_by(workspace_id=workspace_id, sha=sha)
        .first()
    )


def list_for_group(session: Session, workspace_id: int, group_key: str) -> list[RagDocument]:
    """Every row imported under one group (today: one GitHub repository).

    This is what a re-import diffs against to find the rows whose file no
    longer exists (or whose content changed, giving it a new sha and therefore
    a new row) - see rag_admin_service.begin_repo.
    """
    return (
        session.query(RagDocument)
        .filter_by(workspace_id=workspace_id, group_key=group_key)
        .all()
    )


def list_for_workspace(session: Session, workspace_id: int) -> list[RagDocument]:
    return (
        session.query(RagDocument)
        .filter_by(workspace_id=workspace_id)
        .order_by(RagDocument.created_at.desc())
        .all()
    )


def delete(session: Session, workspace_id: int, doc_id: int) -> bool:
    row = get(session, workspace_id, doc_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True
