import logging

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import MAX_ATTACHMENT_BYTES, USE_CELERY
from app.schemas.admin.rag_documents import (
    RagDocumentDeleteResponse,
    RagDocumentItem,
    RagRepoCreate,
    RagRepoImportResponse,
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
from app.tasks.rag_tasks import ingest_rag_document_task

logger = logging.getLogger("dejaq.rag")

router = APIRouter()


def _dispatch_ingest(
    workspace_slug: str, doc_id: int, chunks: list[str], background_tasks: BackgroundTasks
) -> None:
    """Hand the slow embed+index phase to a background job.

    Mirrors the cache-store fallback in routers/openai_compat.py: try Celery
    first, and if it is disabled or its broker is unreachable, fall back to a
    FastAPI BackgroundTasks call of the exact same function - the document
    still ingests, and the catalog row still reports real progress, just from
    this worker process instead of a separate one. An already-working install
    with Celery off must keep working, not fall back to guessing.
    """
    if USE_CELERY:
        try:
            ingest_rag_document_task.apply_async(
                args=(workspace_slug, doc_id, chunks), ignore_result=True
            )
            return
        except Exception:
            logger.warning(
                "Celery dispatch failed for rag ingest doc_id=%s; running in-process",
                doc_id, exc_info=True,
            )
    background_tasks.add_task(rag_admin_service.run_ingest, workspace_slug, doc_id, chunks)


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


@router.post("/workspaces/{workspace_slug}/rag-documents/text", response_model=RagDocumentItem, status_code=202)
def add_rag_text(
    workspace_slug: str,
    body: RagTextCreate,
    background_tasks: BackgroundTasks,
):
    try:
        item, chunks = rag_admin_service.begin_text(workspace_slug, body.title, body.content)
    except (WorkspaceNotFound, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)
    _dispatch_ingest(workspace_slug, item.id, chunks, background_tasks)
    return item


@router.post("/workspaces/{workspace_slug}/rag-documents/url", response_model=RagDocumentItem, status_code=202)
def add_rag_url(
    workspace_slug: str,
    body: RagUrlCreate,
    background_tasks: BackgroundTasks,
):
    try:
        item, chunks = rag_admin_service.begin_url(workspace_slug, body.url, body.title)
    except (WorkspaceNotFound, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)
    _dispatch_ingest(workspace_slug, item.id, chunks, background_tasks)
    return item


@router.post(
    "/workspaces/{workspace_slug}/rag-documents/repo",
    response_model=RagRepoImportResponse,
    status_code=202,
)
async def add_rag_repo(
    workspace_slug: str,
    body: RagRepoCreate,
    background_tasks: BackgroundTasks,
):
    """Import a public GitHub repository as one catalog row per file.

    Same 202 + async shape as the three routes beside it, and each file's slow
    embed phase is dispatched through the very same `_dispatch_ingest`. It runs
    on the threadpool because the fast phase here is not fast: it downloads and
    unpacks a tarball, which would block the event loop from a sync def.
    """
    try:
        result = await run_in_threadpool(
            rag_admin_service.begin_repo, workspace_slug, body.url, body.ref
        )
    except (WorkspaceNotFound, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)
    for item, chunks in result.documents:
        _dispatch_ingest(workspace_slug, item.id, chunks, background_tasks)
    return RagRepoImportResponse(
        repo=result.repo,
        ref=result.ref,
        group_key=result.group_key,
        documents=[item for item, _ in result.documents],
        indexed_files=len(result.documents),
        skipped_files=result.skipped_files,
        removed_documents=result.removed,
    )


@router.post("/workspaces/{workspace_slug}/rag-documents/upload", response_model=RagDocumentItem, status_code=202)
async def upload_rag_document(
    workspace_slug: str,
    background_tasks: BackgroundTasks,
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
        item, chunks = await run_in_threadpool(
            rag_admin_service.begin_upload,
            workspace_slug,
            file.filename,
            data,
            file.content_type,
            title,
        )
    except (WorkspaceNotFound, RagIngestError, RagDisabledError) as exc:
        raise _map_workspace_errors(exc)
    _dispatch_ingest(workspace_slug, item.id, chunks, background_tasks)
    return item


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
