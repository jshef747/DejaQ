import ast
import asyncio
import inspect
import textwrap
from typing import Iterable

from fastapi.routing import APIRoute, APIRouter
from fastapi.testclient import TestClient
from starlette.routing import Mount


def _collect_routes(router) -> list[APIRoute]:
    """Recursively collect APIRoute objects from nested routers and mounts."""
    routes: list[APIRoute] = []
    for route in router.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        elif isinstance(route, (Mount, APIRouter)) and hasattr(route, "routes"):
            routes.extend(_collect_routes(route))
    return routes


def _route_by_method_and_path(routes: Iterable[APIRoute], method: str, path: str) -> APIRoute:
    for route in routes:
        if route.path == path and method in route.methods:
            return route
    raise AssertionError(f"Route {method} {path} not found")


def _endpoint_awaits_feedback_service_submit(endpoint) -> bool:
    source = textwrap.dedent(inspect.getsource(endpoint))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "submit_feedback"
            and isinstance(func.value, ast.Name)
            and func.value.id == "feedback_service"
        ):
            return True
    return False


def test_sync_persistence_admin_routes_are_sync_handlers():
    from app.main import app

    sync_persistence_routes = {
        ("GET", "/admin/v1/orgs"): "list_orgs",
        ("POST", "/admin/v1/orgs"): "create_org",
        ("DELETE", "/admin/v1/orgs/{slug}"): "delete_org",
        ("GET", "/admin/v1/departments"): "list_departments",
        ("POST", "/admin/v1/orgs/{org_slug}/departments"): "create_department",
        ("DELETE", "/admin/v1/orgs/{org_slug}/departments/{dept_slug}"): "delete_department",
        ("GET", "/admin/v1/orgs/{org_slug}/keys"): "list_keys",
        ("POST", "/admin/v1/orgs/{org_slug}/keys"): "generate_key",
        ("DELETE", "/admin/v1/keys/{key_id}"): "revoke_key",
        ("GET", "/admin/v1/stats/orgs"): "org_stats",
        ("GET", "/admin/v1/stats/orgs/{org_slug}/departments"): "department_stats",
        ("GET", "/admin/v1/orgs/{org_slug}/llm-config"): "read_llm_config",
        ("PUT", "/admin/v1/orgs/{org_slug}/llm-config"): "update_llm_config",
        ("GET", "/admin/v1/feedback"): "list_feedback",
    }
    routes = _collect_routes(app.router)

    for (method, path), endpoint_name in sync_persistence_routes.items():
        route = _route_by_method_and_path(routes, method, path)
        assert route.name == endpoint_name
        assert not inspect.iscoroutinefunction(route.endpoint), (
            f"{method} {path} must stay a sync FastAPI handler so blocking "
            "persistence work runs in FastAPI's threadpool"
        )


def test_admin_feedback_submit_is_async_only_for_async_feedback_service():
    from app.main import app
    from app.services import feedback_service

    route = _route_by_method_and_path(_collect_routes(app.router), "POST", "/admin/v1/feedback")

    assert route.name == "submit_feedback"
    assert inspect.iscoroutinefunction(route.endpoint)
    assert inspect.iscoroutinefunction(feedback_service.submit_feedback)
    assert _endpoint_awaits_feedback_service_submit(route.endpoint)


def test_admin_feedback_submit_does_not_run_sync_department_lookup_on_event_loop(
    admin_token_env,
    monkeypatch,
):
    from app.main import app
    from app.services import admin_service, feedback_service

    called_on_event_loop = False

    def list_departments_spy(org_slug=None):
        nonlocal called_on_event_loop
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            called_on_event_loop = True
        return []

    async def submit_feedback_spy(**kwargs):
        return feedback_service.FeedbackResult(status="ok", new_score=1.0)

    admin_token_env("admin-secret")
    monkeypatch.setattr(admin_service, "list_departments", list_departments_spy)
    monkeypatch.setattr(feedback_service, "submit_feedback", submit_feedback_spy)

    response = TestClient(app).post(
        "/admin/v1/feedback",
        headers={"Authorization": "Bearer admin-secret"},
        json={"org": "acme", "response_id": "acme--default:doc-1", "rating": "positive"},
    )

    assert response.status_code == 200
    assert called_on_event_loop is False
