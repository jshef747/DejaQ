from fastapi import APIRouter, Depends, HTTPException

from app.db.models.org import Organization
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


def _resolve_authorized_org(slug: str, ctx: ManagementAuthContext) -> int:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=slug).first()
        if org is None:
            raise HTTPException(status_code=404, detail=f"Organization '{slug}' not found.")
        org_id = org.id
    if not ctx.has_org_access(org_id):
        raise HTTPException(status_code=403, detail=f"Access denied to organization '{slug}'.")
    return org_id


def _credential_service() -> CredentialService:
    try:
        return CredentialService()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/orgs/{org_slug}/credentials", response_model=list[CredentialResponse])
def list_credentials(
    org_slug: str,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    org_id = _resolve_authorized_org(org_slug, ctx)
    service = _credential_service()
    with get_session() as session:
        return service.list_masked(session, org_id)


@router.put("/orgs/{org_slug}/credentials/{provider}", response_model=CredentialResponse)
def upsert_credential(
    org_slug: str,
    provider: ProviderEnum,
    body: CredentialUpsertRequest,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    org_id = _resolve_authorized_org(org_slug, ctx)
    service = _credential_service()
    with get_session() as session:
        row = service.upsert(session, org_id, provider.value, body.api_key)
        return service.to_masked_response(row)


@router.delete("/orgs/{org_slug}/credentials/{provider}", response_model=CredentialDeleteResponse)
def delete_credential(
    org_slug: str,
    provider: ProviderEnum,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    org_id = _resolve_authorized_org(org_slug, ctx)
    service = _credential_service()
    with get_session() as session:
        deleted = service.delete(session, org_id, provider.value)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No {provider.value} credential found.")
    return CredentialDeleteResponse(deleted=True)
