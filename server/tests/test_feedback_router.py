from fastapi.testclient import TestClient

import pytest

from app.main import app
from app.routers import feedback

pytestmark = pytest.mark.no_model


def test_feedback_route_requires_valid_org_key():
    response = TestClient(app).post(
        "/v1/feedback",
        json={"response_id": "acme--default:doc1", "rating": "positive"},
    )

    assert response.status_code == 401


def test_feedback_route_preserves_legacy_deleted_shape(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE
    from app.services.feedback_service import FeedbackResult

    async def _submit_feedback_service(**kwargs):
        return FeedbackResult(status="deleted")

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 7))
    monkeypatch.setattr(feedback, "submit_feedback_service", _submit_feedback_service)

    response = TestClient(app).post(
        "/v1/feedback",
        headers={"Authorization": "Bearer org-key"},
        json={"response_id": "acme--default:doc1", "rating": "negative"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}


def test_feedback_route_returns_escalation_fields_for_interaction_feedback(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE
    from app.schemas.feedback import EscalatedResponse
    from app.services.feedback_service import FeedbackResult

    captured = {}

    async def _submit_feedback_service(**kwargs):
        captured.update(kwargs)
        return FeedbackResult(
            status="ok",
            escalated_response=EscalatedResponse(
                content="better",
                tier="external",
                interaction_id="int_child",
                response_id="acme__eng:doc1",
            ),
            escalation_status="answered",
        )

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 7))
    monkeypatch.setattr(feedback, "submit_feedback_service", _submit_feedback_service)

    response = TestClient(app).post(
        "/v1/feedback",
        headers={"Authorization": "Bearer org-key", "X-DejaQ-Department": "eng"},
        json={
            "interaction_id": "int_parent",
            "rating": "negative",
            "tier": "local",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "escalated_response": {
            "content": "better",
            "tier": "external",
            "interaction_id": "int_child",
            "response_id": "acme__eng:doc1",
        },
        "escalation_status": "answered",
    }
    assert captured["workspace"] == "acme"
    assert captured["workspace_id"] == 7
    assert captured["department"] == "eng"
    assert captured["interaction_id"] == "int_parent"
    assert "tier" not in captured


class _FakeMemory:
    """Minimal cache stand-in: records what was scored or deleted."""

    def __init__(self):
        self.deleted: list[str] = []
        self.score = 0.0

    def get_negative_count(self, doc_id: str) -> int:
        return 0

    def delete_entry(self, doc_id: str) -> bool:
        self.deleted.append(doc_id)
        return True

    def update_score(self, doc_id: str, delta: float) -> float:
        self.score += delta
        return self.score


def _stub_workspace_with_department_named_default(monkeypatch):
    """A workspace whose department is literally NAMED "Default".

    slugify_name("Default") == "default", and dept_repo stores every real
    department as `<workspace>__<slug>` - so its entries live in `acme__default`
    while the no-department fallback would be `acme--default`. Both exist; only
    the middleware's lookup knows which applies.
    """
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 7))
    monkeypatch.setattr(
        _KEY_CACHE,
        "namespace",
        lambda workspace_id, workspace_slug, dept_slug: (
            "acme__default" if dept_slug == "default" else "acme--default"
        ),
    )


def test_feedback_works_for_a_department_actually_named_default(monkeypatch):
    """Re-deriving the namespace from the slugs sent this to `acme--default`,
    mismatched the entry's own namespace, and raised past the router as a 500."""
    from app.services import feedback_service

    memory = _FakeMemory()

    async def _log_feedback(*args, **kwargs):
        return None

    _stub_workspace_with_department_named_default(monkeypatch)
    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)

    response = TestClient(app).post(
        "/v1/feedback",
        headers={"Authorization": "Bearer org-key", "X-DejaQ-Department": "default"},
        json={"response_id": "acme__default:doc1", "rating": "positive"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "new_score": 1.0}


def test_feedback_for_another_workspaces_response_id_is_4xx_not_500(monkeypatch):
    """A genuine mismatch is a caller error. FeedbackNamespaceMismatch subclasses
    neither ValueError nor FeedbackNotFound, so the router used to let it out."""
    _stub_workspace_with_department_named_default(monkeypatch)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/feedback",
        headers={"Authorization": "Bearer org-key", "X-DejaQ-Department": "default"},
        json={"response_id": "someone-else__eng:doc1", "rating": "positive"},
    )

    assert response.status_code == 422
    assert "does not belong" in response.json()["detail"]


def test_feedback_route_forwards_edited_answer_and_returns_edit_fields(monkeypatch):
    """A save reaches the service as one call carrying both the text and the
    positive rating, and its extra fields survive the response shaping — the two
    legacy shortcuts above return status/new_score only."""
    from app.middleware.api_key import _KEY_CACHE
    from app.services.feedback_service import FeedbackResult

    captured = {}

    async def _submit_feedback_service(**kwargs):
        captured.update(kwargs)
        return FeedbackResult(
            status="ok",
            new_score=1.0,
            edit_status="saved",
            response_id="acme__eng:root1",
        )

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 7))
    monkeypatch.setattr(feedback, "submit_feedback_service", _submit_feedback_service)

    response = TestClient(app).post(
        "/v1/feedback",
        headers={"Authorization": "Bearer org-key"},
        json={
            "interaction_id": "int_1",
            "rating": "positive",
            "edited_answer": "the corrected answer",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 200
    assert captured["edited_answer"] == "the corrected answer"
    assert response.json() == {
        "status": "ok",
        "new_score": 1.0,
        "edit_status": "saved",
        "response_id": "acme__eng:root1",
    }


def test_feedback_route_rejects_an_edit_on_a_negative_rating(monkeypatch):
    """A save IS a like; the two are one action, so the pairing is enforced at
    the edge rather than inferred in the service."""
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 7))

    response = TestClient(app).post(
        "/v1/feedback",
        headers={"Authorization": "Bearer org-key"},
        json={"interaction_id": "int_1", "rating": "negative", "edited_answer": "text"},
    )

    assert response.status_code == 422


def test_feedback_route_rejects_an_edit_without_an_interaction_id(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(_KEY_CACHE, "resolve", lambda token: ("acme", 7))

    response = TestClient(app).post(
        "/v1/feedback",
        headers={"Authorization": "Bearer org-key"},
        json={"response_id": "acme--default:doc1", "rating": "positive", "edited_answer": "text"},
    )

    assert response.status_code == 422
