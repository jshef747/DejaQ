from sqlalchemy.orm import Session

from app.db.models.rag_document import RagDocument


def create(
    session: Session,
    workspace_id: int,
    *,
    title: str,
    kind: str,
    source: str,
    source_ref: str | None,
    sha: str,
    char_count: int,
    chunk_count: int,
) -> RagDocument:
    row = RagDocument(
        workspace_id=workspace_id,
        title=title,
        kind=kind,
        source=source,
        source_ref=source_ref,
        sha=sha,
        char_count=char_count,
        chunk_count=chunk_count,
    )
    session.add(row)
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
