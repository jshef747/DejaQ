import inspect
from typing import Literal

from fastapi.testclient import TestClient
from pydantic import BaseModel


class _FeedbackResult(BaseModel):
    status: Literal["ok", "deleted"]
    new_score: float | None = None
    escalation_status: str | None = None
    escalated_response: object | None = None


def test_gateway_route_accepts_org_key_not_supabase_jwt(monkeypatch):
    from app.main import app
    from app.middleware.api_key import _KEY_CACHE
    from app.routers import departments

    def _resolve(token: str):
        if token == "org-key":
            return ("acme", 1)
        return None

    monkeypatch.setattr(_KEY_CACHE, "resolve", _resolve)
    monkeypatch.setattr(departments.dept_repo, "list_depts", lambda _session, org_slug: [])

    client = TestClient(app)

    org_key_response = client.get(
        "/departments",
        headers={"Authorization": "Bearer org-key"},
    )
    # Supabase JWT presented to gateway is treated as org key → invalid → 401
    supabase_jwt_response = client.get(
        "/departments",
        headers={"Authorization": "Bearer supabase-jwt-token"},
    )

    assert org_key_response.status_code == 200
    assert org_key_response.json() == []
    assert supabase_jwt_response.status_code == 401


def test_admin_route_requires_supabase_jwt_not_org_key(monkeypatch):
    """An org key cannot authorize an admin route."""
    from app.main import app
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda _token: ("acme", 1))

    response = TestClient(app).get(
        "/admin/v1/whoami",
        headers={"Authorization": "Bearer org-key"},
    )

    assert response.status_code in (401, 503)


def test_admin_route_does_not_invoke_org_key_middleware(monkeypatch):
    """Admin routes must not trigger org API-key middleware lookup."""
    from app.main import app
    from app.middleware.api_key import _KEY_CACHE

    def _fail_resolve(_token: str):
        raise AssertionError("admin routes must not resolve bearer tokens as org keys")

    monkeypatch.setattr(_KEY_CACHE, "resolve", _fail_resolve)

    # No Supabase config → will return 401 (invalid token from Supabase) or 503
    # but must NOT raise AssertionError from key middleware
    response = TestClient(app).get(
        "/admin/v1/whoami",
        headers={"Authorization": "Bearer any-token"},
    )

    assert response.status_code in (401, 503)


def test_public_feedback_route_uses_gateway_context_and_shared_service(
    monkeypatch,
):
    from app.main import app
    from app.middleware.api_key import _KEY_CACHE
    from app.routers import feedback

    calls = []

    def _resolve(token: str):
        if token == "org-key":
            return ("acme", 1)
        return None

    async def _submit_feedback_service(**kwargs):
        calls.append(kwargs)
        return _FeedbackResult(status="ok", new_score=4.0)

    monkeypatch.setattr(_KEY_CACHE, "resolve", _resolve)
    monkeypatch.setattr(feedback, "submit_feedback_service", _submit_feedback_service)

    response = TestClient(app).post(
        "/v1/feedback",
        headers={
            "Authorization": "Bearer org-key",
            "X-DejaQ-Department": "eng",
        },
        json={
            "response_id": "acme__eng:doc-1",
            "rating": "positive",
            "comment": "helpful",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "new_score": 4.0}
    assert len(calls) == 1
    call = calls[0]
    assert call["response_id"] == "acme__eng:doc-1"
    assert call["rating"] == "positive"
    assert call["comment"] == "helpful"
    assert call["org"] == "acme"
    assert call["department"] == "eng"


def _collect_routes(router):
    """Recursively collect all APIRoute objects from a router and its mounts."""
    from fastapi.routing import APIRoute, APIRouter
    from starlette.routing import Mount

    routes = {}
    for route in router.routes:
        if isinstance(route, APIRoute):
            routes[route.name] = route.endpoint
        elif isinstance(route, (Mount, APIRouter)) and hasattr(route, "routes"):
            routes.update(_collect_routes(route))
    return routes


def test_sync_persistence_admin_routes_are_sync_handlers():
    from app.main import app

    sync_route_names = {
        "list_orgs",
        "create_org",
        "delete_org",
        "list_departments",
        "create_department",
        "delete_department",
        "list_keys",
        "generate_key",
        "revoke_key",
        "delete_revoked_key",
        "org_stats",
        "department_stats",
        "read_llm_config",
        "update_llm_config",
        "list_feedback",
    }

    endpoints = _collect_routes(app.router)

    for name in sync_route_names:
        assert name in endpoints, f"Route '{name}' not found in app — check router registration"
        assert not inspect.iscoroutinefunction(endpoints[name]), f"'{name}' must be a sync handler"
