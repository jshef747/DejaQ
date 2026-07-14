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
    assert captured["org"] == "acme"
    assert captured["workspace_id"] == 7
    assert captured["department"] == "eng"
    assert captured["interaction_id"] == "int_parent"
    assert "tier" not in captured
