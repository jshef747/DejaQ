from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.schemas.admin.stats import DepartmentStatsReport, OrgStatsReport
from app.services import admin_service, stats_service

router = APIRouter()


@router.get("/stats/orgs", response_model=OrgStatsReport)
def org_stats(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
):
    try:
        return stats_service.org_stats(from_date=from_date, to_date=to_date)
    except stats_service.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/stats/orgs/{org_slug}/departments", response_model=DepartmentStatsReport)
def department_stats(
    org_slug: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
):
    if not any(org.slug == org_slug for org in admin_service.list_orgs()):
        raise HTTPException(status_code=404, detail=f"Organization '{org_slug}' not found.")
    try:
        return stats_service.department_stats(org_slug, from_date=from_date, to_date=to_date)
    except stats_service.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
