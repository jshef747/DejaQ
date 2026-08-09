import logging
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import KEY_CACHE_TTL

logger = logging.getLogger("dejaq.middleware.api_key")

# Fallback namespace for requests with no valid API key.
_ANONYMOUS_NAMESPACE = "dejaq_default"


def _db_mtime() -> float:
    """mtime of the SQLite file backing org/dept/key data.

    A shared signal any process can produce just by committing a write —
    unlike in-process invalidate(), this is visible to the server even when
    the mutation came from a separate `dejaq-admin` CLI process.
    """
    try:
        from app.db.base import SessionLocal

        return os.path.getmtime(SessionLocal.kw["bind"].url.database)
    except OSError:
        return 0.0


class _KeyCache:
    """In-process cache of active API keys and department namespaces.

    Loaded from SQLite on first request; refreshed every KEY_CACHE_TTL seconds,
    or immediately once the backing DB file's mtime moves past what was loaded
    (see `_db_mtime`) — this is what lets a `dejaq-admin` mutation in another
    process take effect without waiting out the TTL.
    Structure:
        _keys:  token → (workspace_slug, workspace_id)
        _depts: (workspace_id, dept_slug) → cache_namespace
    """

    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._loaded_at: float = 0.0
        self._db_mtime_at_load: float = 0.0
        self._keys: dict[str, tuple[str, int]] = {}
        self._depts: dict[tuple[int, str], str] = {}
        self._workspace_slugs: dict[int, str] = {}

    def _is_stale(self) -> bool:
        if (time.monotonic() - self._loaded_at) >= self._ttl:
            return True
        return _db_mtime() > self._db_mtime_at_load

    def _refresh(self) -> None:
        from app.db.models.api_key import ApiKey
        from app.db.models.department import Department
        from app.db.models.workspace import Workspace
        from app.db.session import get_session

        new_keys: dict[str, tuple[str, int]] = {}
        new_depts: dict[tuple[int, str], str] = {}
        new_workspace_slugs: dict[int, str] = {}

        try:
            with get_session() as session:
                rows = (
                    session.query(ApiKey, Workspace)
                    .join(Workspace, ApiKey.workspace_id == Workspace.id)
                    .filter(ApiKey.revoked_at.is_(None))
                    .all()
                )
                for api_key, workspace in rows:
                    new_keys[api_key.token] = (workspace.slug, workspace.id)
                    new_workspace_slugs[workspace.id] = workspace.slug

                depts = session.query(Department).all()
                for dept in depts:
                    new_depts[(dept.workspace_id, dept.slug)] = dept.cache_namespace
                    if dept.workspace_id not in new_workspace_slugs:
                        ws_row = session.query(Workspace).filter_by(id=dept.workspace_id).first()
                        if ws_row:
                            new_workspace_slugs[dept.workspace_id] = ws_row.slug

            self._keys = new_keys
            self._depts = new_depts
            self._workspace_slugs = new_workspace_slugs
            self._loaded_at = time.monotonic()
            self._db_mtime_at_load = _db_mtime()
            logger.debug(
                "Key cache refreshed: %d active keys, %d departments",
                len(new_keys),
                len(new_depts),
            )
        except Exception:
            logger.exception("Failed to refresh key cache; retaining previous state")

    def _ensure_fresh(self) -> None:
        if self._is_stale():
            self._refresh()

    def invalidate(self) -> None:
        """Force a DB re-read on the next request.

        Called by admin mutations (workspace/department/key create-delete) so a
        freshly created department or API key resolves immediately instead of
        after the TTL — otherwise the first requests silently fall back to the
        default namespace or 401.
        """
        self._loaded_at = 0.0

    def resolve(self, token: str) -> tuple[str, int] | None:
        """Return (workspace_slug, workspace_id) for an active token, or None if unknown."""
        self._ensure_fresh()
        return self._keys.get(token)

    def namespace(self, workspace_id: int, workspace_slug: str, dept_slug: str | None) -> str:
        """Return cache_namespace for the given workspace+dept, or the workspace default."""
        if dept_slug:
            ns = self._depts.get((workspace_id, dept_slug))
            if ns:
                return ns
            logger.warning(
                "Department slug '%s' not found under workspace '%s'; falling back to default namespace",
                dept_slug,
                workspace_slug,
            )
        return f"{workspace_slug}--default"


_KEY_CACHE = _KeyCache(ttl=KEY_CACHE_TTL)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Resolve workspace and cache namespace from Bearer token + X-DejaQ-Department header.

    Sets on request.state:
        api_key (str | None): raw token
        workspace_slug (str): workspace slug, or "anonymous"
        cache_namespace (str): ChromaDB collection name to use
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith("/admin/v1"):
            return await call_next(request)

        api_key: str | None = None
        workspace_slug = "anonymous"
        workspace_id: int | None = None
        cache_namespace = _ANONYMOUS_NAMESPACE

        auth_header = request.headers.get("Authorization", "")
        if auth_header:
            parts = auth_header.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                api_key = parts[1]
                resolved = _KEY_CACHE.resolve(api_key)
                if resolved:
                    workspace_slug, workspace_id = resolved
                    dept_slug = request.headers.get("X-DejaQ-Department") or None
                    cache_namespace = _KEY_CACHE.namespace(workspace_id, workspace_slug, dept_slug)
                else:
                    redacted = api_key[:8] + "..." if len(api_key) > 8 else api_key
                    logger.warning("Unrecognized API key: %s — serving as anonymous", redacted)
            else:
                logger.warning(
                    "Malformed Authorization header (expected 'Bearer <token>'): %s",
                    auth_header[:30],
                )

        request.state.api_key = api_key
        request.state.workspace_slug = workspace_slug
        request.state.workspace_id = workspace_id
        request.state.cache_namespace = cache_namespace
        return await call_next(request)
