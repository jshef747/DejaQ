import logging
from datetime import datetime

from pydantic import BaseModel

from app.db import api_key_repo, dept_repo, org_repo, user_repo
from app.db.models.api_key import ApiKey
from app.db.models.department import Department
from app.db.models.org import Organization
from app.db.session import get_session
from app.dependencies.management_auth import ManagementAuthContext
from app.schemas.department import DeptRead
from app.schemas.org import OrgRead


class OrgNotFound(Exception):
    def __init__(self, org_slug: str) -> None:
        self.org_slug = org_slug
        super().__init__(f"Organization '{org_slug}' not found.")


class OrgForbidden(Exception):
    def __init__(self, org_slug: str) -> None:
        self.org_slug = org_slug
        super().__init__(f"Access denied to organization '{org_slug}'.")


class DeptNotFound(Exception):
    def __init__(self, org_slug: str, dept_slug: str) -> None:
        self.org_slug = org_slug
        self.dept_slug = dept_slug
        super().__init__(f"Department '{dept_slug}' not found under org '{org_slug}'.")


class KeyNotFound(Exception):
    def __init__(self, key_id: int) -> None:
        self.key_id = key_id
        super().__init__(f"Key id={key_id} not found.")


class KeyForbidden(Exception):
    def __init__(self, key_id: int) -> None:
        self.key_id = key_id
        super().__init__(f"Access denied to key id={key_id}.")


class ActiveKeyCannotBeDeleted(Exception):
    def __init__(self, key_id: int) -> None:
        self.key_id = key_id
        super().__init__(f"Key id={key_id} must be revoked before it can be deleted.")


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


class KeyDeleteResult(BaseModel):
    id: int
    deleted: bool


_SYSTEM_CTX = ManagementAuthContext.system()


def _dept_item(dept: DeptRead, org_slug: str) -> DepartmentItem:
    return DepartmentItem(
        id=dept.id,
        org_slug=org_slug,
        name=dept.name,
        slug=dept.slug,
        cache_namespace=dept.cache_namespace,
        created_at=dept.created_at,
    )


def _check_org_access(ctx: ManagementAuthContext, org: Organization) -> None:
    """Raise OrgForbidden if user actor cannot access org."""
    if not ctx.has_org_access(org.id):
        raise OrgForbidden(org.slug)


def list_orgs(ctx: ManagementAuthContext = _SYSTEM_CTX) -> list[OrgRead]:
    with get_session() as session:
        all_orgs = org_repo.list_orgs(session)
        if ctx.is_system:
            return all_orgs
        accessible_ids = {o.id for o in ctx.accessible_orgs}
        return [o for o in all_orgs if o.id in accessible_ids]


def create_org(name: str, ctx: ManagementAuthContext = _SYSTEM_CTX) -> OrgRead:
    with get_session() as session:
        try:
            new_org = org_repo.create_org(session, name)
        except ValueError as exc:
            message = str(exc)
            slug = message.split("'")[1] if "'" in message else name
            raise DuplicateSlug(slug) from exc

        if not ctx.is_system and ctx.local_user_id is not None:
            user_repo.create_membership_idempotent(session, ctx.local_user_id, new_org.id)

        return new_org


def delete_org(slug: str, ctx: ManagementAuthContext = _SYSTEM_CTX) -> OrgDeleteResult:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=slug).first()
        if org is None:
            raise OrgNotFound(slug)
        _check_org_access(ctx, org)
        dept_pairs = [(d.slug, d.cache_namespace) for d in org.departments]
        departments_removed = len(dept_pairs)
        session.delete(org)
        session.flush()
    for dept_slug, ns in dept_pairs:
        _delete_chroma_namespace(ns)
        _delete_dept_stats(slug, dept_slug)
    return OrgDeleteResult(deleted=True, departments_removed=departments_removed)


def list_departments(
    org_slug: str | None = None,
    ctx: ManagementAuthContext = _SYSTEM_CTX,
) -> list[DepartmentItem]:
    with get_session() as session:
        if org_slug:
            org = session.query(Organization).filter_by(slug=org_slug).first()
            if org is None:
                raise OrgNotFound(org_slug)
            _check_org_access(ctx, org)
            depts = dept_repo.list_depts(session, org_slug=org_slug)
            return [_dept_item(dept, org_slug) for dept in depts]

        rows = (
            session.query(Department, Organization.slug, Organization.id)
            .join(Organization, Department.org_id == Organization.id)
            .order_by(Department.created_at.desc())
            .all()
        )
        result = []
        for dept, row_org_slug, org_id in rows:
            if not ctx.is_system and not ctx.has_org_access(org_id):
                continue
            result.append(_dept_item(DeptRead.model_validate(dept), row_org_slug))
        return result


def create_department(
    org_slug: str,
    name: str,
    ctx: ManagementAuthContext = _SYSTEM_CTX,
) -> DepartmentItem:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=org_slug).first()
        if org is None:
            raise OrgNotFound(org_slug)
        _check_org_access(ctx, org)
        try:
            dept = dept_repo.create_dept(session, org_slug, name)
        except ValueError as exc:
            message = str(exc)
            slug = message.split("'")[1] if "'" in message else name
            raise DuplicateSlug(slug) from exc
        item = _dept_item(dept, org_slug)
    _delete_chroma_namespace(item.cache_namespace)
    _delete_dept_stats(org_slug, item.slug)
    return item


def delete_department(
    org_slug: str,
    dept_slug: str,
    ctx: ManagementAuthContext = _SYSTEM_CTX,
) -> DeptDeleteResult:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=org_slug).first()
        if org is None:
            raise OrgNotFound(org_slug)
        _check_org_access(ctx, org)
        try:
            deleted = dept_repo.delete_dept(session, org_slug, dept_slug)
        except ValueError as exc:
            raise DeptNotFound(org_slug, dept_slug) from exc
        namespace = deleted.cache_namespace
    _delete_chroma_namespace(namespace)
    _delete_dept_stats(org_slug, dept_slug)
    return DeptDeleteResult(deleted=True, cache_namespace=namespace)


def _delete_chroma_namespace(namespace: str) -> None:
    logger = logging.getLogger("dejaq.admin_service")
    try:
        from app.services.memory_chromaDB import _pool
        import chromadb
        from app.config import CHROMA_HOST, CHROMA_PORT

        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        existing = [c.name for c in client.list_collections()]
        if namespace in existing:
            client.delete_collection(namespace)
            logger.info("Deleted ChromaDB collection '%s'", namespace)
            still_there = [c.name for c in client.list_collections()]
            if namespace in still_there:
                logger.error("ChromaDB collection '%s' still exists after delete", namespace)
        _pool.pop(namespace, None)
    except Exception:
        logger.warning("Could not delete ChromaDB collection '%s'", namespace, exc_info=True)


def _delete_dept_stats(org_slug: str, dept_slug: str) -> None:
    logger = logging.getLogger("dejaq.admin_service")
    try:
        import sqlite3
        from app.config import STATS_DB_PATH

        with sqlite3.connect(STATS_DB_PATH) as conn:
            for table, org_col, dept_col in (
                ("requests", "org", "department"),
                ("feedback_log", "org", "department"),
                ("response_interactions", "org_slug", "department"),
            ):
                try:
                    conn.execute(
                        f"DELETE FROM {table} WHERE {org_col} = ? AND {dept_col} = ?",
                        (org_slug, dept_slug),
                    )
                except sqlite3.OperationalError:
                    pass
            conn.commit()
        logger.info("Cleared stats rows for %s/%s", org_slug, dept_slug)
    except Exception:
        logger.warning("Could not clear stats rows for %s/%s", org_slug, dept_slug, exc_info=True)


def list_keys(
    org_slug: str,
    ctx: ManagementAuthContext = _SYSTEM_CTX,
) -> list[KeyListItem]:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=org_slug).first()
        if org is None:
            raise OrgNotFound(org_slug)
        _check_org_access(ctx, org)
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


def generate_key(
    org_slug: str,
    force: bool,
    ctx: ManagementAuthContext = _SYSTEM_CTX,
) -> KeyCreated:
    with get_session() as session:
        org = session.query(Organization).filter_by(slug=org_slug).first()
        if org is None:
            raise OrgNotFound(org_slug)
        _check_org_access(ctx, org)

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


def revoke_key(
    key_id: int,
    ctx: ManagementAuthContext = _SYSTEM_CTX,
) -> KeyRevokeResult:
    with get_session() as session:
        key = session.query(ApiKey).filter_by(id=key_id).first()
        if key is None:
            raise KeyNotFound(key_id)
        org = session.query(Organization).filter_by(id=key.org_id).first()
        if org and not ctx.has_org_access(org.id):
            raise KeyForbidden(key_id)
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


def delete_revoked_key(
    key_id: int,
    ctx: ManagementAuthContext = _SYSTEM_CTX,
) -> KeyDeleteResult:
    with get_session() as session:
        key = session.query(ApiKey).filter_by(id=key_id).first()
        if key is None:
            raise KeyNotFound(key_id)
        org = session.query(Organization).filter_by(id=key.org_id).first()
        if org and not ctx.has_org_access(org.id):
            raise KeyForbidden(key_id)
        if key.revoked_at is None:
            raise ActiveKeyCannotBeDeleted(key_id)
        deleted = api_key_repo.delete_revoked_key(session, key_id)
        if deleted is None:
            raise KeyNotFound(key_id)
        return KeyDeleteResult(id=key_id, deleted=True)
