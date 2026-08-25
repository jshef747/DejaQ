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


# --- Alternative drafts: keeping one of two tied cache entries --------------

def test_feedback_request_accepts_a_draft_choice():
    from app.schemas.feedback import FeedbackRequest

    body = FeedbackRequest(
        interaction_id="int_1",
        rating="positive",
        chosen_draft_response_id="acme--default:doc-b",
        rejected_draft_response_ids=["acme--default:doc-a"],
    )

    assert body.chosen_draft_response_id == "acme--default:doc-b"
    assert body.rejected_draft_response_ids == ["acme--default:doc-a"]


def test_feedback_request_draft_choice_requires_a_positive_rating():
    """Keeping a draft IS a like - one action, not two that share an endpoint."""
    from app.schemas.feedback import FeedbackRequest

    with pytest.raises(ValidationError) as exc:
        FeedbackRequest(
            interaction_id="int_1",
            rating="negative",
            chosen_draft_response_id="acme--default:doc-b",
        )

    assert "positive" in str(exc.value)


def test_feedback_request_draft_choice_requires_an_interaction_id():
    """The interaction record carries the namespace the entries live in, which
    is what proves a client-supplied draft id belongs to this caller."""
    from app.schemas.feedback import FeedbackRequest

    with pytest.raises(ValidationError) as exc:
        FeedbackRequest(
            response_id="acme--default:doc-a",
            rating="positive",
            chosen_draft_response_id="acme--default:doc-b",
        )

    assert "interaction_id" in str(exc.value)


def test_feedback_request_draft_choice_cannot_be_combined_with_an_edit():
    """Two different writes to the same entry in one request, with no defined
    order between them."""
    from app.schemas.feedback import FeedbackRequest

    with pytest.raises(ValidationError):
        FeedbackRequest(
            interaction_id="int_1",
            rating="positive",
            chosen_draft_response_id="acme--default:doc-b",
            edited_answer="a corrected answer",
        )


def test_feedback_request_rejected_ids_alone_are_meaningless():
    from app.schemas.feedback import FeedbackRequest

    with pytest.raises(ValidationError) as exc:
        FeedbackRequest(
            interaction_id="int_1",
            rating="positive",
            rejected_draft_response_ids=["acme--default:doc-a"],
        )

    assert "chosen_draft_response_id" in str(exc.value)


def test_feedback_request_without_a_draft_choice_is_unchanged():
    from app.schemas.feedback import FeedbackRequest

    body = FeedbackRequest(response_id="acme--default:doc1", rating="positive")

    assert body.chosen_draft_response_id is None
    assert body.rejected_draft_response_ids is None
