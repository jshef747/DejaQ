from datetime import datetime

from pydantic import BaseModel

from app.db import api_key_repo, dept_repo, org_repo
from app.db.models.api_key import ApiKey
from app.db.models.department import Department
from app.db.models.org import Organization
from app.db.session import get_session
from app.schemas.department import DeptRead
from app.schemas.org import OrgRead


class OrgNotFound(Exception):
    def __init__(self, org_slug: str) -> None:
        self.org_slug = org_slug
        super().__init__(f"Organization '{org_slug}' not found.")


class DeptNotFound(Exception):
    def __init__(self, org_slug: str, dept_slug: str) -> None:
        self.org_slug = org_slug
        self.dept_slug = dept_slug
        super().__init__(f"Department '{dept_slug}' not found under org '{org_slug}'.")


class KeyNotFound(Exception):
    def __init__(self, key_id: int) -> None:
        self.key_id = key_id
        super().__init__(f"Key id={key_id} not found.")


class DuplicateSlug(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Slug '{slug}' already exists.")


class ActiveKeyExists(Exception):
    def __init__(self, org_slug: str, key_id: int) -> None:
        self.org_slug = org_slug
        self.key_id = key_id
        super().__init__(
            f"Organization '{org_slug}' already has an active key (id={key_id})."
        )


class DepartmentItem(BaseModel):
    id: int
    org_slug: str
    name: str
    slug: str
    cache_namespace: str
    created_at: datetime


class OrgDeleteResult(BaseModel):
    deleted: bool
    departments_removed: int


class DeptDeleteResult(BaseModel):
    deleted: bool
    cache_namespace: str


class KeyCreated(BaseModel):
    id: int
    org_slug: str
    token: str
    created_at: datetime


class KeyListItem(BaseModel):
    id: int
    token_prefix: str
    created_at: datetime
    revoked_at: datetime | None


class KeyRevokeResult(BaseModel):
    id: int
    revoked: bool
    already_revoked: bool
    revoked_at: datetime | None


def _dept_item(dept: DeptRead, org_slug: str) -> DepartmentItem:
    return DepartmentItem(
        id=dept.id,
        org_slug=org_slug,
        name=dept.name,
        slug=dept.slug,
        cache_namespace=dept.cache_namespace,
        created_at=dept.created_at,
    )


def list_orgs() -> list[OrgRead]:
    with get_session() as session:
        return org_repo.list_orgs(session)


def create_org(name: str) -> OrgRead:
    with get_session() as session:
        try:
            return org_repo.create_org(session, name)
        except ValueError as exc:
            message = str(exc)
            slug = message.split("'")[1] if "'" in message else name
            raise DuplicateSlug(slug) from exc


def delete_org(slug: str) -> OrgDeleteResult:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=slug).first()
        if org is None:
            raise OrgNotFound(slug)
        departments_removed = len(org.departments)
        session.delete(org)
        session.flush()
        return OrgDeleteResult(deleted=True, departments_removed=departments_removed)


def list_departments(org_slug: str | None = None) -> list[DepartmentItem]:
    with get_session() as session:
        if org_slug:
            org = session.query(Organization).filter_by(slug=org_slug).first()
            if org is None:
                raise OrgNotFound(org_slug)
            depts = dept_repo.list_depts(session, org_slug=org_slug)
            return [_dept_item(dept, org_slug) for dept in depts]

        rows = (
            session.query(Department, Organization.slug)
            .join(Organization, Department.org_id == Organization.id)
            .order_by(Department.created_at.desc())
            .all()
        )
        return [
            _dept_item(DeptRead.model_validate(dept), row_org_slug)
            for dept, row_org_slug in rows
        ]


def create_department(org_slug: str, name: str) -> DepartmentItem:
    with get_session() as session:
        if session.query(Organization).filter_by(slug=org_slug).first() is None:
            raise OrgNotFound(org_slug)
        try:
            dept = dept_repo.create_dept(session, org_slug, name)
        except ValueError as exc:
            message = str(exc)
            slug = message.split("'")[1] if "'" in message else name
            raise DuplicateSlug(slug) from exc
        return _dept_item(dept, org_slug)


def delete_department(org_slug: str, dept_slug: str) -> DeptDeleteResult:
    with get_session() as session:
        if session.query(Organization).filter_by(slug=org_slug).first() is None:
            raise OrgNotFound(org_slug)
        try:
            deleted = dept_repo.delete_dept(session, org_slug, dept_slug)
        except ValueError as exc:
            raise DeptNotFound(org_slug, dept_slug) from exc
        return DeptDeleteResult(deleted=True, cache_namespace=deleted.cache_namespace)


def list_keys(org_slug: str) -> list[KeyListItem]:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=org_slug).first()
        if org is None:
            raise OrgNotFound(org_slug)
        keys = api_key_repo.list_keys_for_org(session, org.id)
        return [
            KeyListItem(
                id=key.id,
                token_prefix=key.token[:12] + "...",
                created_at=key.created_at,
                revoked_at=key.revoked_at,
            )
            for key in keys
        ]


def generate_key(org_slug: str, force: bool) -> KeyCreated:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=org_slug).first()
        if org is None:
            raise OrgNotFound(org_slug)

        existing = api_key_repo.get_active_key_for_org(session, org.id)
        if existing and not force:
            raise ActiveKeyExists(org_slug, existing.id)
        if existing and force:
            api_key_repo.revoke_key(session, existing.id)

        key = api_key_repo.create_key(session, org.id)
        return KeyCreated(
            id=key.id,
            org_slug=org_slug,
            token=key.token,
            created_at=key.created_at,
        )


def revoke_key(key_id: int) -> KeyRevokeResult:
    with get_session() as session:
        key = session.query(ApiKey).filter_by(id=key_id).first()
        if key is None:
            raise KeyNotFound(key_id)
        already_revoked = key.revoked_at is not None
        revoked = api_key_repo.revoke_key(session, key_id)
        if revoked is None:
            raise KeyNotFound(key_id)
        return KeyRevokeResult(
            id=revoked.id,
            revoked=True,
            already_revoked=already_revoked,
            revoked_at=revoked.revoked_at,
        )
