from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db.models.user import ManagementUser
from app.db.models.user_workspace_membership import UserWorkspaceMembership
from app.db.models.workspace import Workspace


def upsert_user(session: Session, supabase_user_id: str, email: str) -> ManagementUser:
    """Find or create a local user by Supabase user id; refresh email if changed."""
    user = session.query(ManagementUser).filter_by(supabase_user_id=supabase_user_id).first()
    if user is None:
        user = ManagementUser(supabase_user_id=supabase_user_id, email=email)
        session.add(user)
        session.flush()
    elif user.email != email:
        user.email = email
        session.flush()
    return user


def list_memberships(session: Session, user_id: int) -> list[UserWorkspaceMembership]:
    return (
        session.query(UserWorkspaceMembership)
        .filter_by(user_id=user_id)
        .all()
    )


def create_membership_idempotent(session: Session, user_id: int, workspace_id: int) -> UserWorkspaceMembership:
    """Create user-workspace membership; silently ignore duplicate."""
    existing = (
        session.query(UserWorkspaceMembership)
        .filter_by(user_id=user_id, workspace_id=workspace_id)
        .first()
    )
    if existing:
        return existing
    membership = UserWorkspaceMembership(user_id=user_id, workspace_id=workspace_id)
    session.add(membership)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = (
            session.query(UserWorkspaceMembership)
            .filter_by(user_id=user_id, workspace_id=workspace_id)
            .first()
        )
        return existing  # type: ignore[return-value]
    return membership


def get_accessible_workspace_ids(session: Session, user_id: int) -> list[int]:
    rows = session.query(UserWorkspaceMembership.workspace_id).filter_by(user_id=user_id).all()
    return [r[0] for r in rows]


def get_accessible_workspaces(session: Session, user_id: int) -> list[Workspace]:
    workspace_ids = get_accessible_workspace_ids(session, user_id)
    if not workspace_ids:
        return []
    return session.query(Workspace).filter(Workspace.id.in_(workspace_ids)).all()
