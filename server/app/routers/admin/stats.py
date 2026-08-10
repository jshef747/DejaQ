from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.schemas.admin.stats import DepartmentStatsReport, WorkspaceStatsReport
from app.services import admin_service, stats_service

router = APIRouter()


@router.get("/stats/workspaces", response_model=WorkspaceStatsReport)
def workspace_stats(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
):
    try:
        return stats_service.workspace_stats(from_date=from_date, to_date=to_date)
    except stats_service.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/stats/workspaces/{workspace_slug}/departments", response_model=DepartmentStatsReport)
def department_stats(
    workspace_slug: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
):
    workspaces = admin_service.list_workspaces()
    if not any(w.slug == workspace_slug for w in workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_slug}' not found.")
    try:
        return stats_service.department_stats(workspace_slug, from_date=from_date, to_date=to_date)
    except stats_service.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
