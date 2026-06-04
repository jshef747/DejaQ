from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext
from app.schemas.admin.workspaces import WorkspaceCreate, WorkspaceDeleteResponse, WorkspaceItem, WorkspaceUpdate
from app.services import admin_service

router = APIRouter()


@router.get("/workspaces", response_model=list[WorkspaceItem])
def list_workspaces(ctx: ManagementAuthContext = Depends(require_management_auth)):
    return admin_service.list_workspaces(ctx=ctx)


@router.post("/workspaces", response_model=WorkspaceItem, status_code=status.HTTP_201_CREATED)
def create_workspace(
    body: WorkspaceCreate,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        return admin_service.create_workspace(body.name, ctx=ctx)
    except admin_service.DuplicateSlug as exc:
        raise HTTPException(status_code=409, detail="Workspace slug already exists") from exc


@router.patch("/workspaces/{slug}", response_model=WorkspaceItem)
def rename_workspace(
    slug: str,
    body: WorkspaceUpdate,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        return admin_service.rename_workspace(slug, body.name, ctx=ctx)
    except admin_service.WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except admin_service.WorkspaceForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/workspaces/{slug}", response_model=WorkspaceDeleteResponse)
def delete_workspace(
    slug: str,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    try:
        return admin_service.delete_workspace(slug, ctx=ctx)
    except admin_service.WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except admin_service.WorkspaceForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
