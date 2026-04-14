import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.department import Department
from app.db.models.org import Organization
from app.schemas.department import DeptRead


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def create_dept(session: Session, org_slug: str, name: str) -> DeptRead:
    org = session.query(Organization).filter_by(slug=org_slug).first()
    if org is None:
        raise ValueError(f"Organization '{org_slug}' not found.")
    dept_slug = _slugify(name)
    cache_namespace = f"{org_slug}__{dept_slug}"
    dept = Department(
        org_id=org.id,
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
            f"Department '{dept_slug}' already exists under org '{org_slug}'."
        )
    session.refresh(dept)
    return DeptRead.model_validate(dept)


def list_depts(session: Session, org_slug: str | None = None) -> list[DeptRead]:
    query = session.query(Department)
    if org_slug:
        org = session.query(Organization).filter_by(slug=org_slug).first()
        if org is None:
            raise ValueError(f"Organization '{org_slug}' not found.")
        query = query.filter_by(org_id=org.id)
    depts = query.order_by(Department.created_at.desc()).all()
    return [DeptRead.model_validate(d) for d in depts]


def get_dept(session: Session, org_slug: str, dept_slug: str) -> DeptRead | None:
    org = session.query(Organization).filter_by(slug=org_slug).first()
    if org is None:
        return None
    dept = session.query(Department).filter_by(org_id=org.id, slug=dept_slug).first()
    return DeptRead.model_validate(dept) if dept else None


def delete_dept(session: Session, org_slug: str, dept_slug: str) -> DeptRead:
    org = session.query(Organization).filter_by(slug=org_slug).first()
    if org is None:
        raise ValueError(f"Organization '{org_slug}' not found.")
    dept = session.query(Department).filter_by(org_id=org.id, slug=dept_slug).first()
    if dept is None:
        raise ValueError(
            f"Department '{dept_slug}' not found under org '{org_slug}'."
        )
    result = DeptRead.model_validate(dept)
    session.delete(dept)
    session.flush()
    return result
