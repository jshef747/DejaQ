import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.no_model


def test_feedback_request_accepts_legacy_response_id_payload():
    from app.schemas.feedback import FeedbackRequest

    body = FeedbackRequest(response_id="acme--default:doc1", rating="positive")

    assert body.response_id == "acme--default:doc1"
    assert body.interaction_id is None
    assert body.messages is None


def test_feedback_request_accepts_interaction_payload_with_messages_and_tier_metadata():
    from app.schemas.feedback import FeedbackRequest

    body = FeedbackRequest(
        interaction_id="int_123",
        rating="negative",
        tier="local",
        messages=[{"role": "user", "content": "Hello"}],
    )

    assert body.response_id is None
    assert body.interaction_id == "int_123"
    assert body.tier == "local"
    assert body.messages == [{"role": "user", "content": "Hello"}]


def test_feedback_request_requires_a_feedback_target():
    from app.schemas.feedback import FeedbackRequest

    with pytest.raises(ValidationError):
        FeedbackRequest(rating="negative")


def test_feedback_response_serializes_escalation_fields_without_legacy_nulls():
    from app.schemas.feedback import EscalatedResponse, FeedbackResponse

    response = FeedbackResponse(
        status="ok",
        escalated_response=EscalatedResponse(
            content="better answer",
            tier="external",
            interaction_id="int_child",
            response_id="acme__eng:doc1",
        ),
        escalation_status="answered",
    )

    assert response.model_dump(exclude_none=True) == {
        "status": "ok",
        "escalated_response": {
            "content": "better answer",
            "tier": "external",
            "interaction_id": "int_child",
            "response_id": "acme__eng:doc1",
        },
        "escalation_status": "answered",
    }
