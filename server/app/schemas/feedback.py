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
    # Edit & Save: the answer as a person rewrote it. Present only on a save;
    # absent on an ordinary thumbs-up, which is what every existing client sends.
    edited_answer: str | None = None

    @model_validator(mode="after")
    def require_feedback_target(self) -> "FeedbackRequest":
        if not self.response_id and not self.interaction_id:
            raise ValueError("Either response_id or interaction_id is required")
        return self

    @model_validator(mode="after")
    def check_edited_answer(self) -> "FeedbackRequest":
        if self.edited_answer is None:
            return self
        # A save IS a like - the two are one action, not two that happen to
        # share an endpoint - so the pairing is required rather than inferred.
        if self.rating != "positive":
            raise ValueError("edited_answer requires rating='positive'")
        # The interaction record is what carries the namespace, the serving tier
        # and the message hash the create-when-absent path verifies against. A
        # bare response_id cannot stand in for it.
        if not self.interaction_id:
            raise ValueError("edited_answer requires interaction_id")
        return self


class EscalatedResponse(BaseModel):
    content: str
    tier: Literal["local", "external"]
    interaction_id: str | None = None
    response_id: str | None = None


class FeedbackResponse(BaseModel):
    status: Literal["ok", "deleted"]
    new_score: float | None = None
    # Set only when the request carried an edited_answer. "saved" overwrote an
    # existing entry, "created" wrote one the pipeline never did, "not_cached"
    # means there was nothing to overwrite and no usable replay to build from
    # (an attachment turn), "message_mismatch" means the replay did not match
    # the interaction. Mirrors answer_edit.EditStatus - edit both together.
    edit_status: Literal["saved", "created", "not_cached", "message_mismatch"] | None = None
    # The entry the edit landed on, when it differs from the one the client
    # held: an alias-served id redirects to its root, and a created entry is
    # keyed by a freshly derived normalized query.
    response_id: str | None = None
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
