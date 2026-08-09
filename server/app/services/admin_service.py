import logging
from datetime import datetime

from pydantic import BaseModel

from app.db import api_key_repo, dept_repo, workspace_repo
from app.db.models.api_key import ApiKey
from app.db.models.department import Department
from app.db.models.workspace import Workspace
from app.db.session import get_session
from app.schemas.department import DeptRead
from app.schemas.workspace import WorkspaceRead


class WorkspaceNotFound(Exception):
    def __init__(self, workspace_slug: str) -> None:
        self.workspace_slug = workspace_slug
        super().__init__(f"Workspace '{workspace_slug}' not found.")


class DeptNotFound(Exception):
    def __init__(self, workspace_slug: str, dept_slug: str) -> None:
        self.workspace_slug = workspace_slug
        self.dept_slug = dept_slug
        super().__init__(f"Department '{dept_slug}' not found under workspace '{workspace_slug}'.")


class KeyNotFound(Exception):
    def __init__(self, key_id: int) -> None:
        self.key_id = key_id
        super().__init__(f"Key id={key_id} not found.")


class ActiveKeyCannotBeDeleted(Exception):
    def __init__(self, key_id: int) -> None:
        self.key_id = key_id
        super().__init__(f"Key id={key_id} must be revoked before it can be deleted.")


class DuplicateSlug(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Slug '{slug}' already exists.")


class ActiveKeyExists(Exception):
    def __init__(self, workspace_slug: str, key_id: int) -> None:
        self.workspace_slug = workspace_slug
        self.key_id = key_id
        super().__init__(
            f"Workspace '{workspace_slug}' already has an active key (id={key_id})."
        )


class DepartmentItem(BaseModel):
    id: int
    workspace_slug: str
    name: str
    slug: str
    cache_namespace: str
    created_at: datetime


class WorkspaceDeleteResult(BaseModel):
    deleted: bool
    departments_removed: int


class DeptDeleteResult(BaseModel):
    deleted: bool
    cache_namespace: str


class KeyCreated(BaseModel):
    id: int
    workspace_slug: str
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


def _dept_item(dept: DeptRead, workspace_slug: str) -> DepartmentItem:
    return DepartmentItem(
        id=dept.id,
        workspace_slug=workspace_slug,
        name=dept.name,
        slug=dept.slug,
        cache_namespace=dept.cache_namespace,
        created_at=dept.created_at,
    )


def list_workspaces() -> list[WorkspaceRead]:
    with get_session() as session:
        return workspace_repo.list_workspaces(session)


def _invalidate_key_cache() -> None:
    """Bust the API-key middleware cache so admin mutations take effect immediately."""
    try:
        from app.middleware.api_key import _KEY_CACHE

        _KEY_CACHE.invalidate()
    except Exception:
        logging.getLogger("dejaq.admin_service").warning("Key-cache invalidation failed", exc_info=True)


def create_workspace(name: str) -> WorkspaceRead:
    with get_session() as session:
        try:
            new_workspace = workspace_repo.create_workspace(session, name)
        except ValueError as exc:
            message = str(exc)
            slug = message.split("'")[1] if "'" in message else name
            raise DuplicateSlug(slug) from exc

    _invalidate_key_cache()
    return new_workspace


def rename_workspace(slug: str, new_name: str) -> WorkspaceRead:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=slug).first()
        if workspace is None:
            raise WorkspaceNotFound(slug)
        return workspace_repo.rename_workspace(session, slug, new_name)


def delete_workspace(slug: str) -> WorkspaceDeleteResult:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=slug).first()
        if workspace is None:
            raise WorkspaceNotFound(slug)
        namespaces = [d.cache_namespace for d in workspace.departments]
        departments_removed = len(namespaces)
        session.delete(workspace)
        session.flush()
    for ns in namespaces:
        _delete_chroma_namespace(ns)
    # The workspace's RAG knowledge base is its own Chroma collection, separate
    # from the department cache namespaces above. Its catalog rows cascade-delete
    # with the workspace (FK), but the vectors must be dropped explicitly.
    _delete_rag_namespace(slug)
    _invalidate_key_cache()
    return WorkspaceDeleteResult(deleted=True, departments_removed=departments_removed)


def _delete_rag_namespace(workspace_slug: str) -> None:
    try:
        from app.services import rag_service

        rag_service.delete_namespace(rag_service.rag_namespace(workspace_slug))
    except Exception:
        logging.getLogger("dejaq.admin_service").warning(
            "Could not delete RAG collection for workspace '%s'", workspace_slug, exc_info=True
        )


def list_departments(workspace_slug: str | None = None) -> list[DepartmentItem]:
    with get_session() as session:
        if workspace_slug:
            workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
            if workspace is None:
                raise WorkspaceNotFound(workspace_slug)
            depts = dept_repo.list_depts(session, workspace_slug=workspace_slug)
            return [_dept_item(dept, workspace_slug) for dept in depts]

        rows = (
            session.query(Department, Workspace.slug)
            .join(Workspace, Department.workspace_id == Workspace.id)
            .order_by(Department.created_at.desc())
            .all()
        )
        return [
            _dept_item(DeptRead.model_validate(dept), row_workspace_slug)
            for dept, row_workspace_slug in rows
        ]


def create_department(workspace_slug: str, name: str) -> DepartmentItem:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
        if workspace is None:
            raise WorkspaceNotFound(workspace_slug)
        try:
            dept = dept_repo.create_dept(session, workspace_slug, name)
        except ValueError as exc:
            message = str(exc)
            slug = message.split("'")[1] if "'" in message else name
            raise DuplicateSlug(slug) from exc
        item = _dept_item(dept, workspace_slug)
    _invalidate_key_cache()
    return item


def rename_department(
    workspace_slug: str,
    dept_slug: str,
    new_name: str,
) -> DepartmentItem:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
        if workspace is None:
            raise WorkspaceNotFound(workspace_slug)
        try:
            dept = dept_repo.rename_dept(session, workspace_slug, dept_slug, new_name)
        except ValueError as exc:
            raise DeptNotFound(workspace_slug, dept_slug) from exc
        return _dept_item(dept, workspace_slug)


def delete_department(
    workspace_slug: str,
    dept_slug: str,
) -> DeptDeleteResult:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
        if workspace is None:
            raise WorkspaceNotFound(workspace_slug)
        try:
            deleted = dept_repo.delete_dept(session, workspace_slug, dept_slug)
        except ValueError as exc:
            raise DeptNotFound(workspace_slug, dept_slug) from exc
        namespace = deleted.cache_namespace
    _delete_chroma_namespace(namespace)
    _invalidate_key_cache()
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
        _pool.pop(namespace, None)
    except Exception:
        logger.warning("Could not delete ChromaDB collection '%s'", namespace, exc_info=True)


def list_keys(workspace_slug: str) -> list[KeyListItem]:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
        if workspace is None:
            raise WorkspaceNotFound(workspace_slug)
        keys = api_key_repo.list_keys_for_workspace(session, workspace.id)
        return [
            KeyListItem(
                id=key.id,
                token_prefix=key.token[:12] + "...",
                created_at=key.created_at,
                revoked_at=key.revoked_at,
            )
            for key in keys
        ]


def generate_key(workspace_slug: str, force: bool) -> KeyCreated:
    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
        if workspace is None:
            raise WorkspaceNotFound(workspace_slug)

        existing = api_key_repo.get_active_key_for_workspace(session, workspace.id)
        if existing and not force:
            raise ActiveKeyExists(workspace_slug, existing.id)
        if existing and force:
            api_key_repo.revoke_key(session, existing.id)

        key = api_key_repo.create_key(session, workspace.id)
        result = KeyCreated(
            id=key.id,
            workspace_slug=workspace_slug,
            token=key.token,
            created_at=key.created_at,
        )
    _invalidate_key_cache()
    return result


def revoke_key(key_id: int) -> KeyRevokeResult:
    with get_session() as session:
        key = session.query(ApiKey).filter_by(id=key_id).first()
        if key is None:
            raise KeyNotFound(key_id)
        already_revoked = key.revoked_at is not None
        revoked = api_key_repo.revoke_key(session, key_id)
        if revoked is None:
            raise KeyNotFound(key_id)
        result = KeyRevokeResult(
            id=revoked.id,
            revoked=True,
            already_revoked=already_revoked,
            revoked_at=revoked.revoked_at,
        )
    _invalidate_key_cache()
    return result


def delete_revoked_key(key_id: int) -> KeyDeleteResult:
    with get_session() as session:
        key = session.query(ApiKey).filter_by(id=key_id).first()
        if key is None:
            raise KeyNotFound(key_id)
        if key.revoked_at is None:
            raise ActiveKeyCannotBeDeleted(key_id)
        deleted = api_key_repo.delete_revoked_key(session, key_id)
        if deleted is None:
            raise KeyNotFound(key_id)
        return KeyDeleteResult(id=key_id, deleted=True)
