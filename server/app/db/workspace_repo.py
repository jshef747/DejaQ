from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.workspace import Workspace
from app.db.slug import slugify_name
from app.schemas.workspace import WorkspaceRead


def create_workspace(session: Session, name: str) -> WorkspaceRead:
    slug = slugify_name(name)
    workspace = Workspace(name=name, slug=slug)
    session.add(workspace)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise ValueError(f"A workspace with slug '{slug}' already exists.")
    session.refresh(workspace)
    return WorkspaceRead.model_validate(workspace)


def list_workspaces(session: Session) -> list[WorkspaceRead]:
    workspaces = session.query(Workspace).order_by(Workspace.created_at.desc()).all()
    return [WorkspaceRead.model_validate(w) for w in workspaces]


def get_workspace_by_slug(session: Session, slug: str) -> WorkspaceRead | None:
    workspace = session.query(Workspace).filter_by(slug=slug).first()
    return WorkspaceRead.model_validate(workspace) if workspace else None


def delete_workspace(session: Session, slug: str) -> int:
    workspace = session.query(Workspace).filter_by(slug=slug).first()
    if workspace is None:
        raise ValueError(f"Workspace '{slug}' not found.")
    dept_count = len(workspace.departments)
    session.delete(workspace)
    session.flush()
    return dept_count
