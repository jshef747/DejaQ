"""Unit tests for management auth: Supabase SDK-backed JWT validation."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext, WorkspaceRef


# ── Helpers ──────────────────────────────────────────────────────────────────

def _probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    def probe(ctx: ManagementAuthContext = require_management_auth):  # type: ignore[assignment]
        from fastapi import Depends
        return {"actor_type": ctx.actor_type, "email": ctx.email}

    from fastapi import Depends

    app2 = FastAPI()

    @app2.get("/probe", dependencies=[Depends(require_management_auth)])
    def probe2():
        return {"authorized": True}

    return app2


def _make_sb_user(supabase_id: str = "user-123", email: str = "demo@dejaq.local"):
    user = MagicMock()
    user.id = supabase_id
    user.email = email
    resp = MagicMock()
    resp.user = user
    return resp


def _mock_upsert_and_orgs(monkeypatch, local_user_id=1, orgs=None):
    from app.services import management_auth_service

    local_user = MagicMock()
    local_user.id = local_user_id

    if orgs is None:
        orgs = []

    monkeypatch.setattr(
        "app.services.management_auth_service.user_repo.upsert_user",
        lambda session, supabase_user_id, email: local_user,
    )
    monkeypatch.setattr(
        "app.services.management_auth_service.user_repo.get_accessible_workspaces",
        lambda session, uid: orgs,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestManagementAuthContextStructure:
    def test_system_actor_has_full_access(self):
        ctx = ManagementAuthContext.system()
        assert ctx.actor_type == "system"
        assert ctx.is_system
        assert ctx.has_workspace_access(999)
        assert ctx.has_workspace_access_by_slug("any-slug")

    def test_user_actor_limited_to_memberships(self):
        from datetime import datetime, timezone
        ws = WorkspaceRef(id=1, name="Acme", slug="acme", created_at=datetime.now(timezone.utc))
        ctx = ManagementAuthContext(
            actor_type="user",
            local_user_id=1,
            supabase_user_id="u1",
            email="a@b.com",
            accessible_workspaces=[ws],
        )
        assert not ctx.is_system
        assert ctx.has_workspace_access(1)
        assert ctx.has_workspace_access_by_slug("acme")
        assert not ctx.has_workspace_access(2)
        assert not ctx.has_workspace_access_by_slug("globex")

    def test_user_with_no_memberships_has_empty_workspace_access(self):
        ctx = ManagementAuthContext(
            actor_type="user",
            local_user_id=1,
            supabase_user_id="u1",
            email="a@b.com",
            accessible_workspaces=[],
        )
        assert not ctx.has_workspace_access(1)
        assert not ctx.has_workspace_access_by_slug("any")


class TestLocalAuthMode:
    def test_local_dev_context_has_full_access(self):
        ctx = ManagementAuthContext.local_dev()
        assert ctx.is_system
        assert ctx.email == "dev@localhost"
        assert ctx.has_workspace_access(123)
        assert ctx.has_workspace_access_by_slug("anything")

    def test_dependency_bypasses_token_in_local_mode(self, monkeypatch):
        monkeypatch.setattr("app.config.AUTH_MODE", "local")
        client = TestClient(_probe_app())
        # No Authorization header required in local mode.
        resp = client.get("/probe")
        assert resp.status_code == 200
        assert resp.json() == {"authorized": True}


class TestSupabaseAuthValidation:
    def test_missing_auth_header_returns_401(self, monkeypatch):
        monkeypatch.setattr("app.config.AUTH_MODE", "supabase")
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        client = TestClient(_probe_app())
        resp = client.get("/probe")
        assert resp.status_code == 401

    def test_valid_token_builds_user_context(self, monkeypatch, isolated_org_db):
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        sb_resp = _make_sb_user("user-123", "demo@dejaq.local")
        mock_client = MagicMock()
        mock_client.get_user.return_value = sb_resp

        _mock_upsert_and_orgs(monkeypatch)

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            from app.services.management_auth_service import validate_token_and_build_context
            ctx = validate_token_and_build_context("valid-token")

        assert ctx.actor_type == "user"
        assert ctx.supabase_user_id == "user-123"
        assert ctx.email == "demo@dejaq.local"

    def test_invalid_token_raises_auth_invalid(self, monkeypatch, isolated_org_db):
        from supabase_auth.errors import AuthApiError
        from app.services.management_auth_service import SupabaseAuthInvalid

        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        mock_client = MagicMock()
        mock_client.get_user.side_effect = AuthApiError("invalid JWT", 401, None)

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            from app.services.management_auth_service import validate_token_and_build_context
            with pytest.raises(SupabaseAuthInvalid):
                validate_token_and_build_context("expired-token")

    def test_sdk_transport_failure_raises_unavailable(self, monkeypatch, isolated_org_db):
        from app.services.management_auth_service import SupabaseAuthUnavailable

        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        mock_client = MagicMock()
        mock_client.get_user.side_effect = ConnectionError("network failure")

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            from app.services.management_auth_service import validate_token_and_build_context
            with pytest.raises(SupabaseAuthUnavailable):
                validate_token_and_build_context("any-token")

    def test_transport_failure_does_not_mutate_local_user(self, monkeypatch, isolated_org_db):
        """SDK transport failure must not create/update local user rows."""
        from app.services.management_auth_service import SupabaseAuthUnavailable

        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        mock_client = MagicMock()
        mock_client.get_user.side_effect = RuntimeError("SDK crash")

        upsert_called = []

        def _fail_upsert(*args, **kwargs):
            upsert_called.append(True)
            raise AssertionError("upsert must not be called on transport failure")

        monkeypatch.setattr("app.services.management_auth_service.user_repo.upsert_user", _fail_upsert)

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            from app.services.management_auth_service import validate_token_and_build_context
            with pytest.raises(SupabaseAuthUnavailable):
                validate_token_and_build_context("any-token")

        assert not upsert_called

    def test_missing_supabase_config_raises_not_configured(self, monkeypatch):
        from app.services.management_auth_service import SupabaseAuthNotConfigured

        monkeypatch.setenv("SUPABASE_URL", "")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "")
        monkeypatch.setattr("app.services.management_auth_service.config.SUPABASE_URL", "")
        monkeypatch.setattr("app.services.management_auth_service.config.SUPABASE_ANON_KEY", "")

        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        from app.services.management_auth_service import validate_token_and_build_context
        with pytest.raises(SupabaseAuthNotConfigured):
            validate_token_and_build_context("any-token")

    def test_user_upsert_on_first_request(self, monkeypatch, isolated_org_db):
        from app.db.session import get_session
        from app.db.models.user import ManagementUser

        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        sb_resp = _make_sb_user("uid-new", "new@example.com")
        mock_client = MagicMock()
        mock_client.get_user.return_value = sb_resp

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            from app.services.management_auth_service import validate_token_and_build_context
            ctx = validate_token_and_build_context("valid-token")

        assert ctx.supabase_user_id == "uid-new"

        with get_session() as session:
            user = session.query(ManagementUser).filter_by(supabase_user_id="uid-new").first()
            assert user is not None
            assert user.email == "new@example.com"

    def test_email_refresh_on_repeat_request(self, monkeypatch, isolated_org_db):
        from app.db.session import get_session
        from app.db.models.user import ManagementUser
        from app.db import user_repo

        with get_session() as session:
            user_repo.upsert_user(session, "uid-existing", "old@example.com")

        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        sb_resp = _make_sb_user("uid-existing", "new@example.com")
        mock_client = MagicMock()
        mock_client.get_user.return_value = sb_resp

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            from app.services.management_auth_service import validate_token_and_build_context
            validate_token_and_build_context("valid-token")

        with get_session() as session:
            user = session.query(ManagementUser).filter_by(supabase_user_id="uid-existing").first()
            assert user.email == "new@example.com"

    def test_empty_memberships_returns_empty_org_list(self, monkeypatch, isolated_org_db):
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        sb_resp = _make_sb_user("uid-nomember", "nomember@example.com")
        mock_client = MagicMock()
        mock_client.get_user.return_value = sb_resp

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            from app.services.management_auth_service import validate_token_and_build_context
            ctx = validate_token_and_build_context("valid-token")

        assert ctx.accessible_workspaces == []

    def test_no_get_session_or_manual_jwt_in_auth_service(self):
        """Verify no local JWT decoding, JWKS, or get_session in management_auth_service."""
        import inspect
        from app.services import management_auth_service

        source = inspect.getsource(management_auth_service)
        assert "get_session" not in source or "from app.db.session import get_session" in source
        assert "jwt.decode" not in source
        assert "JWKS" not in source.upper()
        assert "jwks" not in source
        assert "decode_token" not in source
        # The service must use get_user not get_session
        assert "get_user" in source

    def test_service_role_excluded_from_request_auth(self):
        """Service-role credentials must not appear in request-time auth path."""
        import inspect
        from app.dependencies import admin_auth

        source = inspect.getsource(admin_auth)
        assert "SERVICE_ROLE" not in source
        assert "service_role" not in source.lower() or "get_service_role_client" not in source

    def test_fastapi_dependency_returns_503_when_not_configured(self, monkeypatch):
        from app.services.management_auth_service import SupabaseAuthNotConfigured, _get_auth_client
        _get_auth_client.cache_clear()
        monkeypatch.setattr("app.config.AUTH_MODE", "supabase")
        monkeypatch.setattr("app.services.management_auth_service.config.SUPABASE_URL", "")
        monkeypatch.setattr("app.services.management_auth_service.config.SUPABASE_ANON_KEY", "")

        client = TestClient(_probe_app())
        resp = client.get("/probe", headers={"Authorization": "Bearer anything"})
        assert resp.status_code == 503

    def test_fastapi_dependency_returns_401_for_invalid_token(self, monkeypatch, isolated_org_db):
        from supabase_auth.errors import AuthApiError
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        monkeypatch.setattr("app.config.AUTH_MODE", "supabase")
        monkeypatch.setattr("app.services.management_auth_service.config.SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setattr("app.services.management_auth_service.config.SUPABASE_ANON_KEY", "anon-key")

        mock_client = MagicMock()
        mock_client.get_user.side_effect = AuthApiError("expired", 401, None)

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            client = TestClient(_probe_app())
            resp = client.get("/probe", headers={"Authorization": "Bearer expired-token"})
        assert resp.status_code == 401

    def test_fastapi_dependency_returns_503_on_transport_failure(self, monkeypatch, isolated_org_db):
        from app.services.management_auth_service import _get_auth_client
        _get_auth_client.cache_clear()

        monkeypatch.setattr("app.config.AUTH_MODE", "supabase")
        monkeypatch.setattr("app.services.management_auth_service.config.SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setattr("app.services.management_auth_service.config.SUPABASE_ANON_KEY", "anon-key")

        mock_client = MagicMock()
        mock_client.get_user.side_effect = ConnectionError("network down")

        with patch("app.services.management_auth_service._get_auth_client", return_value=mock_client):
            client = TestClient(_probe_app())
            resp = client.get("/probe", headers={"Authorization": "Bearer any-token"})
        assert resp.status_code == 503
