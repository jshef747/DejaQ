import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db import rag_document_repo
from app.db.session import get_session
from app.dependencies.auth import ResolvedWorkspace, require_org_key

logger = logging.getLogger("dejaq.router.rag_documents_public")

router = APIRouter()


class RagDocumentPickerItem(BaseModel):
    id: int
    title: str
    kind: str


@router.get("/rag-documents", response_model=list[RagDocumentPickerItem])
def list_rag_documents(
    workspace: ResolvedWorkspace = Depends(require_org_key),
) -> list[RagDocumentPickerItem]:
    """List the workspace's knowledge-base documents for the chat app's `@`
    picker. Mirrors GET /departments exactly (same auth dependency, same
    shape): the admin catalog lives behind loopback-only /admin/v1/*, and the
    chat app has no other way to see what documents exist.

    Only what a picker needs — id, title, kind — never document content.
    """
    # Built INSIDE the session block: get_session() commits on exit, which
    # expires every loaded attribute (SQLAlchemy's expire_on_commit default),
    # and the session is closed by the time the `with` exits — reading a
    # column off `d` afterwards is a detached-instance error, not a cache hit.
    with get_session() as session:
        docs = rag_document_repo.list_for_workspace(session, workspace.workspace_id)
        items = [RagDocumentPickerItem(id=d.id, title=d.title, kind=d.kind) for d in docs]

    logger.info("GET /rag-documents workspace=%s count=%d", workspace.workspace_slug, len(items))
    return items
