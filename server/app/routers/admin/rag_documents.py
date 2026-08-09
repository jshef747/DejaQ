import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import MAX_ATTACHMENT_BYTES, RAG_ENABLED
from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext
from app.schemas.admin.rag_documents import (
    RagDocumentDeleteResponse,
    RagDocumentItem,
    RagTextCreate,
    RagUrlCreate,
)
from app.services import rag_admin_service
from app.services.admin_service import WorkspaceForbidden, WorkspaceNotFound
from app.services.rag_admin_service import (
    RagDisabledError,
    RagDocumentNotFound,
    RagIngestError,
)

logger = logging.getLogger("dejaq.rag")

router = APIRouter()


def _map_workspace_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkspaceNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, WorkspaceForbidden):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, RagDocumentNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RagIngestError):
        # The input reached us fine; we just could not extract usable text from it.
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, RagDisabledError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/workspaces/{workspace_slug}/rag-documents", response_model=list[RagDocumentItem])
def list_rag_documents(
    workspace_slug: str,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        return rag_admin_service.list_documents(workspace_slug, ctx)
    except (WorkspaceNotFound, WorkspaceForbidden) as exc:
        raise _map_workspace_errors(exc)


@router.post("/workspaces/{workspace_slug}/rag-documents/text", response_model=RagDocumentItem)
def add_rag_text(
    workspace_slug: str,
    body: RagTextCreate,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        return rag_admin_service.add_text(workspace_slug, body.title, body.content, ctx)
    except (WorkspaceNotFound, WorkspaceForbidden, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)


@router.post("/workspaces/{workspace_slug}/rag-documents/url", response_model=RagDocumentItem)
def add_rag_url(
    workspace_slug: str,
    body: RagUrlCreate,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        return rag_admin_service.add_url(workspace_slug, body.url, body.title, ctx)
    except (WorkspaceNotFound, WorkspaceForbidden, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)


@router.post("/workspaces/{workspace_slug}/rag-documents/upload", response_model=RagDocumentItem)
async def upload_rag_document(
    workspace_slug: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    if not RAG_ENABLED:
        raise HTTPException(status_code=400, detail="RAG is disabled on this server.")
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds the {MAX_ATTACHMENT_BYTES}-byte limit.",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        return await run_in_threadpool(
            rag_admin_service.add_upload,
            workspace_slug,
            file.filename,
            data,
            file.content_type,
            title,
            ctx,
        )
    except (WorkspaceNotFound, WorkspaceForbidden, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)


@router.delete(
    "/workspaces/{workspace_slug}/rag-documents/{doc_id}",
    response_model=RagDocumentDeleteResponse,
)
def delete_rag_document(
    workspace_slug: str,
    doc_id: int,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        rag_admin_service.delete_document(workspace_slug, doc_id, ctx)
    except (WorkspaceNotFound, WorkspaceForbidden, RagDocumentNotFound) as exc:
        raise _map_workspace_errors(exc)
    return RagDocumentDeleteResponse(id=doc_id, deleted=True)
