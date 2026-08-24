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
    # Alternative drafts: which of the two tied cache entries the user kept.
    # The chosen entry takes the ordinary +1.0, which is what eventually ends
    # the tie (see CACHE_DRAFTS_MAX_SCORE_GAP). The rejected ids are recorded
    # for analysis only - they are NOT penalised, because by the tie-breaker's
    # own definition the loser was a high-quality match that another user may
    # well prefer.
    chosen_draft_response_id: str | None = None
    rejected_draft_response_ids: list[str] | None = None

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

    @model_validator(mode="after")
    def check_draft_choice(self) -> "FeedbackRequest":
        if self.chosen_draft_response_id is None:
            if self.rejected_draft_response_ids:
                raise ValueError(
                    "rejected_draft_response_ids requires chosen_draft_response_id"
                )
            return self
        # Keeping a draft IS a like, exactly as saving an edit is - one action,
        # not two that share an endpoint.
        if self.rating != "positive":
            raise ValueError("chosen_draft_response_id requires rating='positive'")
        # The interaction record carries the namespace the entries actually live
        # in, which is what proves a client-supplied draft id belongs to this
        # caller before anything is scored.
        if not self.interaction_id:
            raise ValueError("chosen_draft_response_id requires interaction_id")
        # Two different writes to the same entry in one request, with no defined
        # order between them. A client that wants both should pick first, then
        # edit the answer it kept.
        if self.edited_answer is not None:
            raise ValueError(
                "chosen_draft_response_id and edited_answer cannot be combined"
            )
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
    # Set only when the request carried a draft choice. "recorded" scored the
    # chosen entry; "not_found" means it was already gone (evicted, or deleted
    # by somebody's thumbs-down) - the pick is simply lost, not an error.
    draft_choice: Literal["recorded", "not_found"] | None = None
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
