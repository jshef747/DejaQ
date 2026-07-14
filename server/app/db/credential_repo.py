from sqlalchemy.orm import Session

from app.db.models.workspace_provider_credentials import WorkspaceProviderCredentials


def upsert_credential(
    session: Session,
    workspace_id: int,
    provider: str,
    encrypted_key: str,
) -> WorkspaceProviderCredentials:
    row = get_credential(session, workspace_id, provider)
    if row is None:
        row = WorkspaceProviderCredentials(workspace_id=workspace_id, provider=provider, encrypted_key=encrypted_key)
        session.add(row)
    else:
        row.encrypted_key = encrypted_key

    session.flush()
    session.refresh(row)
    return row


def get_credential(session: Session, workspace_id: int, provider: str) -> WorkspaceProviderCredentials | None:
    return (
        session.query(WorkspaceProviderCredentials)
        .filter_by(workspace_id=workspace_id, provider=provider)
        .first()
    )


def list_credentials(session: Session, workspace_id: int) -> list[WorkspaceProviderCredentials]:
    return (
        session.query(WorkspaceProviderCredentials)
        .filter_by(workspace_id=workspace_id)
        .order_by(WorkspaceProviderCredentials.provider.asc())
        .all()
    )


def delete_credential(session: Session, workspace_id: int, provider: str) -> bool:
    row = get_credential(session, workspace_id, provider)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True
