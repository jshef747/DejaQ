from fastapi import APIRouter, HTTPException

from app.db.models.workspace import Workspace
from app.db.session import get_session
from app.schemas.credentials import (
    CredentialDeleteResponse,
    CredentialResponse,
    CredentialUpsertRequest,
)
from app.services.credential_service import CredentialService

router = APIRouter()


def _resolve_workspace_id(slug: str) -> int:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=slug).first()
        if workspace is None:
            raise HTTPException(status_code=404, detail=f"Workspace '{slug}' not found.")
        return workspace.id


def _credential_service() -> CredentialService:
    try:
        return CredentialService()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/workspaces/{workspace_slug}/credentials", response_model=list[CredentialResponse])
def list_credentials(workspace_slug: str):
    workspace_id = _resolve_workspace_id(workspace_slug)
    service = _credential_service()
    with get_session() as session:
        return service.list_masked(session, workspace_id)


@router.put("/workspaces/{workspace_slug}/credentials/{provider}", response_model=CredentialResponse)
def upsert_credential(
    workspace_slug: str,
    provider: str,
    body: CredentialUpsertRequest,
):
    workspace_id = _resolve_workspace_id(workspace_slug)
    service = _credential_service()
    with get_session() as session:
        try:
            row = service.upsert(session, workspace_id, provider, body.api_key)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return service.to_masked_response(row)


@router.delete("/workspaces/{workspace_slug}/credentials/{provider}", response_model=CredentialDeleteResponse)
def delete_credential(workspace_slug: str, provider: str):
    workspace_id = _resolve_workspace_id(workspace_slug)
    service = _credential_service()
    with get_session() as session:
        try:
            deleted = service.delete(session, workspace_id, provider)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No {provider} credential found.")
    return CredentialDeleteResponse(deleted=True)
