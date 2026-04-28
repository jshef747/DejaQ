from sqlalchemy.orm import Session

from app.db.models.org_provider_credentials import OrgProviderCredentials


def upsert_credential(
    session: Session,
    org_id: int,
    provider: str,
    encrypted_key: str,
) -> OrgProviderCredentials:
    row = get_credential(session, org_id, provider)
    if row is None:
        row = OrgProviderCredentials(org_id=org_id, provider=provider, encrypted_key=encrypted_key)
        session.add(row)
    else:
        row.encrypted_key = encrypted_key

    session.flush()
    session.refresh(row)
    return row


def get_credential(session: Session, org_id: int, provider: str) -> OrgProviderCredentials | None:
    return (
        session.query(OrgProviderCredentials)
        .filter_by(org_id=org_id, provider=provider)
        .first()
    )


def list_credentials(session: Session, org_id: int) -> list[OrgProviderCredentials]:
    return (
        session.query(OrgProviderCredentials)
        .filter_by(org_id=org_id)
        .order_by(OrgProviderCredentials.provider.asc())
        .all()
    )


def delete_credential(session: Session, org_id: int, provider: str) -> bool:
    row = get_credential(session, org_id, provider)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True
