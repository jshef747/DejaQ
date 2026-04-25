from fastapi import APIRouter, HTTPException, status

from app.schemas.admin.orgs import OrgCreate, OrgDeleteResponse, OrgItem
from app.services import admin_service

router = APIRouter()


@router.get("/orgs", response_model=list[OrgItem])
def list_orgs():
    return admin_service.list_orgs()


@router.post("/orgs", response_model=OrgItem, status_code=status.HTTP_201_CREATED)
def create_org(body: OrgCreate):
    try:
        return admin_service.create_org(body.name)
    except admin_service.DuplicateSlug as exc:
        raise HTTPException(status_code=409, detail="Organization slug already exists") from exc


@router.delete("/orgs/{slug}", response_model=OrgDeleteResponse)
def delete_org(slug: str):
    try:
        return admin_service.delete_org(slug)
    except admin_service.OrgNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
