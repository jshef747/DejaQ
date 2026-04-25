from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.admin.keys import KeyCreated, KeyItem, KeyRevokeResponse
from app.services import admin_service

router = APIRouter()


@router.get("/orgs/{org_slug}/keys", response_model=list[KeyItem])
def list_keys(org_slug: str):
    try:
        return admin_service.list_keys(org_slug)
    except admin_service.OrgNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/orgs/{org_slug}/keys",
    response_model=KeyCreated,
    status_code=status.HTTP_201_CREATED,
)
def generate_key(org_slug: str, force: bool = Query(default=False)):
    try:
        return admin_service.generate_key(org_slug, force=force)
    except admin_service.OrgNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except admin_service.ActiveKeyExists as exc:
        raise HTTPException(
            status_code=409,
            detail="Active key exists; use ?force=true to rotate it",
        ) from exc


@router.delete("/keys/{key_id}", response_model=KeyRevokeResponse)
def revoke_key(key_id: int):
    try:
        return admin_service.revoke_key(key_id)
    except admin_service.KeyNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
