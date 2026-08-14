import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import MAX_ATTACHMENT_BYTES
from app.schemas.admin.rag_documents import (
    RagDocumentDeleteResponse,
    RagDocumentItem,
    RagTextCreate,
    RagUrlCreate,
)
from app.services import rag_admin_service
from app.services.admin_service import WorkspaceNotFound
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
    if isinstance(exc, RagDocumentNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RagIngestError):
        # The input reached us fine; we just could not extract usable text from it.
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, RagDisabledError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/workspaces/{workspace_slug}/rag-documents", response_model=list[RagDocumentItem])
def list_rag_documents(workspace_slug: str):
    try:
        return rag_admin_service.list_documents(workspace_slug)
    except WorkspaceNotFound as exc:
        raise _map_workspace_errors(exc)


@router.post("/workspaces/{workspace_slug}/rag-documents/text", response_model=RagDocumentItem)
def add_rag_text(
    workspace_slug: str,
    body: RagTextCreate,
):
    try:
        return rag_admin_service.add_text(workspace_slug, body.title, body.content)
    except (WorkspaceNotFound, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)


@router.post("/workspaces/{workspace_slug}/rag-documents/url", response_model=RagDocumentItem)
def add_rag_url(
    workspace_slug: str,
    body: RagUrlCreate,
):
    try:
        return rag_admin_service.add_url(workspace_slug, body.url, body.title)
    except (WorkspaceNotFound, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)


@router.post("/workspaces/{workspace_slug}/rag-documents/upload", response_model=RagDocumentItem)
async def upload_rag_document(
    workspace_slug: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
):
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
        )
    except (WorkspaceNotFound, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)


@router.delete(
    "/workspaces/{workspace_slug}/rag-documents/{doc_id}",
    response_model=RagDocumentDeleteResponse,
)
def delete_rag_document(
    workspace_slug: str,
    doc_id: int,
):
    try:
        rag_admin_service.delete_document(workspace_slug, doc_id)
    except (WorkspaceNotFound, RagDocumentNotFound) as exc:
        raise _map_workspace_errors(exc)
    return RagDocumentDeleteResponse(id=doc_id, deleted=True)
