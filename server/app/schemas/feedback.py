from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    response_id: str | None = None
    interaction_id: str | None = None
    rating: Literal["positive", "negative"]
    comment: str | None = None
    tier: Literal["cache", "local", "external"] | None = None
    messages: list[dict] | None = None

    @model_validator(mode="after")
    def require_feedback_target(self) -> "FeedbackRequest":
        if not self.response_id and not self.interaction_id:
            raise ValueError("Either response_id or interaction_id is required")
        return self


class EscalatedResponse(BaseModel):
    content: str
    tier: Literal["local", "external"]
    interaction_id: str | None = None
    response_id: str | None = None


class FeedbackResponse(BaseModel):
    status: Literal["ok", "deleted"]
    new_score: float | None = None
    escalated_response: EscalatedResponse | None = None
    escalation_status: (
        Literal[
            "answered",
            "not_requested",
            "no_further_escalation",
            "no_credential",
            "provider_error",
            "timeout",
            "message_mismatch",
            "already_escalated",
        ]
        | None
    ) = None
