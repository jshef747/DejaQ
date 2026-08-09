from fastapi import APIRouter, HTTPException, status

from app.schemas.admin.workspaces import WorkspaceCreate, WorkspaceDeleteResponse, WorkspaceItem, WorkspaceUpdate
from app.services import admin_service

router = APIRouter()


@router.get("/workspaces", response_model=list[WorkspaceItem])
def list_workspaces():
    return admin_service.list_workspaces()


@router.post("/workspaces", response_model=WorkspaceItem, status_code=status.HTTP_201_CREATED)
def create_workspace(body: WorkspaceCreate):
    try:
        return admin_service.create_workspace(body.name)
    except admin_service.DuplicateSlug as exc:
        raise HTTPException(status_code=409, detail="Workspace slug already exists") from exc


@router.patch("/workspaces/{slug}", response_model=WorkspaceItem)
def rename_workspace(slug: str, body: WorkspaceUpdate):
    try:
        return admin_service.rename_workspace(slug, body.name)
    except admin_service.WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/workspaces/{slug}", response_model=WorkspaceDeleteResponse)
def delete_workspace(slug: str):
    try:
        return admin_service.delete_workspace(slug)
    except admin_service.WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
