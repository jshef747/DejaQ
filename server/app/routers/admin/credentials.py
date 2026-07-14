from fastapi import APIRouter, Depends, HTTPException

from app.db.models.workspace import Workspace
from app.db.session import get_session
from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext
from app.schemas.credentials import (
    CredentialDeleteResponse,
    CredentialResponse,
    CredentialUpsertRequest,
    ProviderEnum,
)
from app.services.credential_service import CredentialService

router = APIRouter()


def _resolve_authorized_workspace(slug: str, ctx: ManagementAuthContext) -> int:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=slug).first()
        if workspace is None:
            raise HTTPException(status_code=404, detail=f"Workspace '{slug}' not found.")
        workspace_id = workspace.id
    if not ctx.has_workspace_access(workspace_id):
        raise HTTPException(status_code=403, detail=f"Access denied to workspace '{slug}'.")
    return workspace_id


def _credential_service() -> CredentialService:
    try:
        return CredentialService()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/workspaces/{workspace_slug}/credentials", response_model=list[CredentialResponse])
def list_credentials(
    workspace_slug: str,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    workspace_id = _resolve_authorized_workspace(workspace_slug, ctx)
    service = _credential_service()
    with get_session() as session:
        return service.list_masked(session, workspace_id)


@router.put("/workspaces/{workspace_slug}/credentials/{provider}", response_model=CredentialResponse)
def upsert_credential(
    workspace_slug: str,
    provider: ProviderEnum,
    body: CredentialUpsertRequest,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    workspace_id = _resolve_authorized_workspace(workspace_slug, ctx)
    service = _credential_service()
    with get_session() as session:
        row = service.upsert(session, workspace_id, provider.value, body.api_key)
        return service.to_masked_response(row)


@router.delete("/workspaces/{workspace_slug}/credentials/{provider}", response_model=CredentialDeleteResponse)
def delete_credential(
    workspace_slug: str,
    provider: ProviderEnum,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    workspace_id = _resolve_authorized_workspace(workspace_slug, ctx)
    service = _credential_service()
    with get_session() as session:
        deleted = service.delete(session, workspace_id, provider.value)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No {provider.value} credential found.")
    return CredentialDeleteResponse(deleted=True)
