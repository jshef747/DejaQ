"""Unit tests for management auth: local dev-admin context (the only mode)."""
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext, WorkspaceRef


# ── Helpers ──────────────────────────────────────────────────────────────────

def _probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(require_management_auth)])
    def probe():
        return {"authorized": True}

    return app


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

    def test_dependency_returns_local_dev_context_unconditionally(self):
        ctx = require_management_auth()
        assert ctx == ManagementAuthContext.local_dev()

    def test_no_auth_header_required(self):
        client = TestClient(_probe_app())
        resp = client.get("/probe")
        assert resp.status_code == 200
        assert resp.json() == {"authorized": True}

    def test_arbitrary_auth_header_is_ignored_not_validated(self):
        """The management API never inspects the Authorization header; any value works."""
        client = TestClient(_probe_app())
        resp = client.get("/probe", headers={"Authorization": "Bearer whatever-nonsense"})
        assert resp.status_code == 200
        assert resp.json() == {"authorized": True}
