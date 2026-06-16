from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.department import Department
from app.db.models.workspace import Workspace
from app.db.slug import slugify_name
from app.schemas.department import DeptRead


def create_dept(session: Session, workspace_slug: str, name: str) -> DeptRead:
    workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
    if workspace is None:
        raise ValueError(f"Workspace '{workspace_slug}' not found.")
    dept_slug = slugify_name(name)
    cache_namespace = f"{workspace_slug}__{dept_slug}"
    dept = Department(
        workspace_id=workspace.id,
        name=name,
        slug=dept_slug,
        cache_namespace=cache_namespace,
    )
    session.add(dept)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise ValueError(
            f"Department '{dept_slug}' already exists under workspace '{workspace_slug}'."
        )
    session.refresh(dept)
    return DeptRead.model_validate(dept)


def list_depts(session: Session, workspace_slug: str | None = None) -> list[DeptRead]:
    query = session.query(Department)
    if workspace_slug:
        workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
        if workspace is None:
            raise ValueError(f"Workspace '{workspace_slug}' not found.")
        query = query.filter_by(workspace_id=workspace.id)
    depts = query.order_by(Department.created_at.desc()).all()
    return [DeptRead.model_validate(d) for d in depts]


def get_dept(session: Session, workspace_slug: str, dept_slug: str) -> DeptRead | None:
    workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
    if workspace is None:
        return None
    dept = session.query(Department).filter_by(workspace_id=workspace.id, slug=dept_slug).first()
    return DeptRead.model_validate(dept) if dept else None


def rename_dept(session: Session, workspace_slug: str, dept_slug: str, new_name: str) -> DeptRead:
    workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
    if workspace is None:
        raise ValueError(f"Workspace '{workspace_slug}' not found.")
    dept = session.query(Department).filter_by(workspace_id=workspace.id, slug=dept_slug).first()
    if dept is None:
        raise ValueError(f"Department '{dept_slug}' not found under workspace '{workspace_slug}'.")
    dept.name = new_name
    session.flush()
    session.refresh(dept)
    return DeptRead.model_validate(dept)


def delete_dept(session: Session, workspace_slug: str, dept_slug: str) -> DeptRead:
    workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
    if workspace is None:
        raise ValueError(f"Workspace '{workspace_slug}' not found.")
    dept = session.query(Department).filter_by(workspace_id=workspace.id, slug=dept_slug).first()
    if dept is None:
        raise ValueError(
            f"Department '{dept_slug}' not found under workspace '{workspace_slug}'."
        )
    result = DeptRead.model_validate(dept)
    session.delete(dept)
    session.flush()
    return result
