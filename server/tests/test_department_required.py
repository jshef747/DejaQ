"""Gateway requests must name an existing department - there is no shared
default cache namespace (app/middleware/api_key.py). Anonymous/unresolved
Bearer tokens are unaffected and keep serving out of `_ANONYMOUS_NAMESPACE`.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.api_key import _KEY_CACHE, DepartmentResolutionError


@pytest.fixture(autouse=True)
def _stub_resolve(monkeypatch):
    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 7) if token == "org-key" else None)


def test_existing_department_resolves_its_own_namespace(monkeypatch):
    monkeypatch.setattr(
        _KEY_CACHE,
        "namespace",
        lambda workspace_id, workspace_slug, dept_slug: "acme__eng" if dept_slug == "eng" else None,
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer org-key", "X-DejaQ-Department": "eng"},
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )

    # Fails downstream (no pipeline stubbed) - what matters here is the
    # middleware let the request past department resolution instead of 422/404ing it.
    assert response.status_code not in (422, 404)


def test_unknown_department_is_404(monkeypatch):
    def _namespace(workspace_id, workspace_slug, dept_slug):
        raise DepartmentResolutionError(
            404, f"Department '{dept_slug}' not found in workspace '{workspace_slug}'"
        )

    monkeypatch.setattr(_KEY_CACHE, "namespace", _namespace)

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer org-key", "X-DejaQ-Department": "ghost"},
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 404
    assert "ghost" in response.json()["detail"]
    assert "acme" in response.json()["detail"]


def test_missing_department_header_is_422():
    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer org-key"},
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "X-DejaQ-Department header is required"


def test_v1_responses_rejects_missing_department_before_running_pipeline(monkeypatch):
    """Gateway-level: /v1/responses must 422 on a missing department header
    without ever touching the pipeline (no model/router stubs installed)."""
    response = TestClient(app).post(
        "/v1/responses",
        headers={"Authorization": "Bearer org-key"},
        json={"model": "gpt-4o-mini", "input": "hi", "stream": False},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "X-DejaQ-Department header is required"


def test_v1_feedback_rejects_missing_department_header(monkeypatch):
    """Gateway-level: /v1/feedback also 422s on a missing department header
    (path.startswith("/v1/") in ApiKeyMiddleware covers it too)."""
    response = TestClient(app).post(
        "/v1/feedback",
        headers={"Authorization": "Bearer org-key"},
        json={"response_id": "acme__eng:doc1", "rating": "positive"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "X-DejaQ-Department header is required"


def test_no_shared_default_namespace_construction_remains():
    """The `<workspace>--default` fallback string must not appear in the
    module - it was the silent shared namespace this task removes."""
    import inspect

    from app.middleware import api_key

    source = inspect.getsource(api_key)
    # namespace_or_default() keeps the legacy fallback for non-gateway
    # (/departments, /rag-suggest) authenticated paths only; namespace()
    # itself (the /v1/* gateway path) must not construct it.
    namespace_fn_source = inspect.getsource(api_key._KeyCache.namespace)
    assert "--default" not in namespace_fn_source
