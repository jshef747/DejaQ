import pytest
from pydantic import ValidationError


def test_llm_config_update_rejects_empty_body_and_out_of_range_threshold():
    from app.schemas.admin.llm_config import LlmConfigUpdate

    with pytest.raises(ValidationError):
        LlmConfigUpdate()

    with pytest.raises(ValidationError):
        LlmConfigUpdate(routing_threshold=1.5)

    assert LlmConfigUpdate(routing_threshold=0.0).routing_threshold == 0.0
    assert LlmConfigUpdate(external_model=None).external_model is None


def test_admin_feedback_request_defaults_department():
    from app.schemas.admin.feedback import AdminFeedbackRequest

    body = AdminFeedbackRequest(
        workspace="acme",
        response_id="acme--default:doc1",
        rating="positive",
    )

    assert body.department == "default"
