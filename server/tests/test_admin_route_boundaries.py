import inspect
from typing import Literal

from fastapi.testclient import TestClient
from pydantic import BaseModel


class _FeedbackResult(BaseModel):
    status: Literal["ok", "deleted"]
    new_score: float | None = None


def test_gateway_route_accepts_org_key_not_admin_token(admin_token_env, monkeypatch):
    from app.main import app
    from app.middleware.api_key import _KEY_CACHE
    from app.routers import departments

    admin_token_env("admin-secret")

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
    admin_token_response = client.get(
        "/departments",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert org_key_response.status_code == 200
    assert org_key_response.json() == []
    assert admin_token_response.status_code == 401
    assert admin_token_response.json() == {"detail": "Invalid or revoked API key"}


def test_org_key_does_not_authorize_admin_route(admin_token_env, monkeypatch):
    from app.main import app
    from app.middleware.api_key import _KEY_CACHE

    admin_token_env("admin-secret")
    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda _token: ("acme", 1))

    response = TestClient(app).get(
        "/admin/v1/whoami",
        headers={"Authorization": "Bearer org-key"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid admin token"}


def test_admin_route_accepts_admin_token_without_gateway_lookup(admin_token_env, monkeypatch):
    from app.main import app
    from app.middleware.api_key import _KEY_CACHE

    def _fail_resolve(_token: str):
        raise AssertionError("admin routes must not resolve bearer tokens as org keys")

    admin_token_env("admin-secret")
    monkeypatch.setattr(_KEY_CACHE, "resolve", _fail_resolve)

    response = TestClient(app).get(
        "/admin/v1/whoami",
        headers={"Authorization": "Bearer admin-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"authorized": True}


def test_public_feedback_route_uses_gateway_context_and_shared_service(
    admin_token_env, monkeypatch
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

    admin_token_env("admin-secret")
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
    assert calls == [
        {
            "response_id": "acme__eng:doc-1",
            "rating": "positive",
            "comment": "helpful",
            "org": "acme",
            "department": "eng",
            "validate_namespace": False,
        }
    ]


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
