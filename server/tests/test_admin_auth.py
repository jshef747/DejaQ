"""Unit tests for management auth: local dev-admin context (the only mode)."""
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext


# ── Helpers ──────────────────────────────────────────────────────────────────

def _probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(require_management_auth)])
    def probe():
        return {"authorized": True}

    return app


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLocalAuthMode:
    def test_local_dev_context_carries_the_dev_admin_identity(self):
        ctx = ManagementAuthContext.local_dev()
        assert ctx.email == "dev@localhost"

    def test_dependency_returns_local_dev_context_unconditionally(self):
        ctx = require_management_auth()
        assert ctx == ManagementAuthContext.local_dev()

    def test_no_auth_header_required(self):
        client = TestClient(_probe_app())
        resp = client.get("/probe")
        assert resp.status_code == 200
