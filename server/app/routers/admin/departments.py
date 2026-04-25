from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.admin.departments import (
    DepartmentCreate,
    DepartmentDeleteResponse,
    DepartmentItem,
)
from app.services import admin_service

router = APIRouter()


@router.get("/departments", response_model=list[DepartmentItem])
def list_departments(org: str | None = Query(default=None)):
    try:
        return admin_service.list_departments(org_slug=org)
    except admin_service.OrgNotFound:
        return []


@router.post(
    "/orgs/{org_slug}/departments",
    response_model=DepartmentItem,
    status_code=status.HTTP_201_CREATED,
)
def create_department(org_slug: str, body: DepartmentCreate):
    try:
        return admin_service.create_department(org_slug, body.name)
    except admin_service.OrgNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except admin_service.DuplicateSlug as exc:
        raise HTTPException(status_code=409, detail="Department slug already exists") from exc


@router.delete(
    "/orgs/{org_slug}/departments/{dept_slug}",
    response_model=DepartmentDeleteResponse,
)
def delete_department(org_slug: str, dept_slug: str):
    try:
        return admin_service.delete_department(org_slug, dept_slug)
    except (admin_service.OrgNotFound, admin_service.DeptNotFound) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
