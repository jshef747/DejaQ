import logging
from typing import NamedTuple

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.middleware.api_key import _KEY_CACHE

logger = logging.getLogger("dejaq.dependencies.auth")

_bearer = HTTPBearer(auto_error=False)


class ResolvedWorkspace(NamedTuple):
    workspace_slug: str
    workspace_id: int


def require_org_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ResolvedWorkspace:
    """FastAPI dependency: resolve Bearer token to a workspace via the key cache.

    Returns ResolvedWorkspace(workspace_slug, workspace_id) on success.
    Raises 401 if the token is missing, unrecognized, or revoked.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    resolved = _KEY_CACHE.resolve(credentials.credentials)
    if resolved is None:
        redacted = credentials.credentials[:8] + "..." if len(credentials.credentials) > 8 else credentials.credentials
        logger.warning("Invalid API key presented to auth dependency: %s", redacted)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    workspace_slug, workspace_id = resolved
    return ResolvedWorkspace(workspace_slug=workspace_slug, workspace_id=workspace_id)
