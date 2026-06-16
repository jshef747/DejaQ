from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext
from app.schemas.admin.stats import DepartmentStatsReport, WorkspaceStatsReport
from app.services import admin_service, stats_service

router = APIRouter()


@router.get("/stats/workspaces", response_model=WorkspaceStatsReport)
def workspace_stats(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    accessible_slugs = None if ctx.is_system else {w.slug for w in ctx.accessible_workspaces}
    try:
        return stats_service.workspace_stats(from_date=from_date, to_date=to_date, accessible_workspace_slugs=accessible_slugs)
    except stats_service.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/stats/workspaces/{workspace_slug}/departments", response_model=DepartmentStatsReport)
def department_stats(
    workspace_slug: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    workspaces = admin_service.list_workspaces(ctx=ManagementAuthContext.system())
    if not any(w.slug == workspace_slug for w in workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_slug}' not found.")
    if not ctx.has_workspace_access_by_slug(workspace_slug):
        raise HTTPException(status_code=403, detail=f"Access denied to workspace '{workspace_slug}'.")
    try:
        return stats_service.department_stats(workspace_slug, from_date=from_date, to_date=to_date)
    except stats_service.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
