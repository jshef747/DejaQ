import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.org import Organization
from app.schemas.org import OrgRead


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def create_org(session: Session, name: str) -> OrgRead:
    slug = _slugify(name)
    org = Organization(name=name, slug=slug)
    session.add(org)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise ValueError(f"An organization with slug '{slug}' already exists.")
    session.refresh(org)
    return OrgRead.model_validate(org)


def list_orgs(session: Session) -> list[OrgRead]:
    orgs = session.query(Organization).order_by(Organization.created_at.desc()).all()
    return [OrgRead.model_validate(o) for o in orgs]


def get_org_by_slug(session: Session, slug: str) -> OrgRead | None:
    org = session.query(Organization).filter_by(slug=slug).first()
    return OrgRead.model_validate(org) if org else None


def delete_org(session: Session, slug: str) -> int:
    org = session.query(Organization).filter_by(slug=slug).first()
    if org is None:
        raise ValueError(f"Organization '{slug}' not found.")
    dept_count = len(org.departments)
    session.delete(org)
    session.flush()
    return dept_count
