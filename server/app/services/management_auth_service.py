import logging
from functools import lru_cache

from supabase_auth import SyncGoTrueClient
from supabase_auth.errors import AuthApiError

import app.config as config
from app.db import user_repo
from app.db.session import get_session
from app.dependencies.management_auth import ManagementAuthContext, WorkspaceRef

logger = logging.getLogger("dejaq.services.management_auth")


class SupabaseAuthNotConfigured(Exception):
    pass


class SupabaseAuthUnavailable(Exception):
    pass


class SupabaseAuthInvalid(Exception):
    pass


@lru_cache(maxsize=1)
def _get_auth_client() -> SyncGoTrueClient:
    """Return a cached anon-key Supabase Auth client for request-time token validation."""
    url = config.SUPABASE_URL.strip()
    key = config.SUPABASE_ANON_KEY.strip()
    if not url or not key:
        raise SupabaseAuthNotConfigured("SUPABASE_URL and SUPABASE_ANON_KEY must be set")
    auth_url = url.rstrip("/") + "/auth/v1"
    return SyncGoTrueClient(
        url=auth_url,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        auto_refresh_token=False,
        persist_session=False,
    )


def validate_token_and_build_context(access_token: str) -> ManagementAuthContext:
    """Validate a Supabase access token and build a user ManagementAuthContext.

    Raises:
        SupabaseAuthNotConfigured: Supabase URL/key not configured.
        SupabaseAuthUnavailable: SDK transport or server failure.
        SupabaseAuthInvalid: Token is missing, invalid, expired, or rejected.
    """
    try:
        client = _get_auth_client()
    except SupabaseAuthNotConfigured:
        raise

    try:
        response = client.get_user(access_token)
    except AuthApiError as exc:
        raise SupabaseAuthInvalid("Token rejected by Supabase Auth") from exc
    except Exception as exc:
        logger.error("Supabase Auth SDK transport failure")
        raise SupabaseAuthUnavailable("Supabase Auth unavailable") from exc

    if response is None or response.user is None:
        raise SupabaseAuthInvalid("Token validation returned no user")

    sb_user = response.user
    supabase_user_id = sb_user.id
    email = sb_user.email or ""

    with get_session() as session:
        local_user = user_repo.upsert_user(session, supabase_user_id, email)
        workspaces = user_repo.get_accessible_workspaces(session, local_user.id)
        workspace_refs = [
            WorkspaceRef(id=ws.id, name=ws.name, slug=ws.slug, created_at=ws.created_at)
            for ws in workspaces
        ]
        local_user_id = local_user.id

    return ManagementAuthContext(
        actor_type="user",
        local_user_id=local_user_id,
        supabase_user_id=supabase_user_id,
        email=email,
        accessible_workspaces=workspace_refs,
    )


def get_service_role_client() -> SyncGoTrueClient:
    """Return a service-role Supabase Auth client for setup/seed paths only."""
    url = config.SUPABASE_URL.strip()
    key = config.SUPABASE_SERVICE_ROLE_KEY.strip()
    if not url or not key:
        raise SupabaseAuthNotConfigured(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set for seed operations"
        )
    auth_url = url.rstrip("/") + "/auth/v1"
    return SyncGoTrueClient(
        url=auth_url,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        auto_refresh_token=False,
        persist_session=False,
    )
