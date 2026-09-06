from fastapi import APIRouter, HTTPException, Query

from app.schemas.admin.cache_entries import (
    CacheAnswerEdit,
    CacheEntryDeleteResult,
    CacheEntryDetail,
    CacheEntryEditResult,
    CacheEntryPage,
)
from app.services import cache_admin_service
from app.services.admin_service import DeptNotFound, WorkspaceNotFound
from app.services.cache_admin_service import CacheEntryNotFound, ChromaUnavailable

router = APIRouter()


def _map_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, (WorkspaceNotFound, DeptNotFound, CacheEntryNotFound)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ChromaUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.get("/workspaces/{workspace_slug}/cache-entries", response_model=CacheEntryPage)
def list_cache_entries(
    workspace_slug: str,
    department: str,
    limit: int = Query(default=cache_admin_service.DEFAULT_LIMIT, ge=1, le=cache_admin_service.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    try:
        return cache_admin_service.list_cache_entries(workspace_slug, department, limit=limit, offset=offset)
    except (WorkspaceNotFound, DeptNotFound, ChromaUnavailable) as exc:
        raise _map_errors(exc)


@router.get(
    "/workspaces/{workspace_slug}/cache-entries/{entry_id}",
    response_model=CacheEntryDetail,
)
def get_cache_entry(workspace_slug: str, entry_id: str, department: str):
    try:
        return cache_admin_service.get_cache_entry_detail(workspace_slug, department, entry_id)
    except (WorkspaceNotFound, DeptNotFound, CacheEntryNotFound, ChromaUnavailable) as exc:
        raise _map_errors(exc)


@router.put(
    "/workspaces/{workspace_slug}/cache-entries/{entry_id}",
    response_model=CacheEntryEditResult,
)
def edit_cache_entry(
    workspace_slug: str,
    entry_id: str,
    department: str,
    body: CacheAnswerEdit,
):
    try:
        return cache_admin_service.edit_cache_entry_answer(
            workspace_slug, department, entry_id, body.answer
        )
    except (WorkspaceNotFound, DeptNotFound, CacheEntryNotFound, ChromaUnavailable, ValueError) as exc:
        raise _map_errors(exc)


@router.delete(
    "/workspaces/{workspace_slug}/cache-entries/{entry_id}",
    response_model=CacheEntryDeleteResult,
)
def delete_cache_entry(
    workspace_slug: str,
    entry_id: str,
    department: str,
):
    try:
        return cache_admin_service.delete_cache_entry(workspace_slug, department, entry_id)
    except (WorkspaceNotFound, DeptNotFound, CacheEntryNotFound, ChromaUnavailable) as exc:
        raise _map_errors(exc)
