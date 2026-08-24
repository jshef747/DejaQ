from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PROMPT_FIELDS = (
    "enricher_system_prompt",
    "normalizer_system_prompt",
    "validator_system_prompt",
    "validator_image_system_prompt",
    "adjuster_system_prompt",
    "generalizer_system_prompt",
    "local_model_system_prompt",
)


class LlmConfigResponse(BaseModel):
    # None when the workspace has no external_model override and no
    # DEJAQ_EXTERNAL_MODEL env default is set - "no model configured", not a
    # silently substituted one.
    external_model: str | None
    local_model: str
    # Read-only: whether local_model reports Ollama's "vision" capability via
    # /api/show. None means unknown (Ollama unreachable, or the model isn't
    # installed there). Nothing reads this to route or gate anything yet -
    # it exists purely so an admin can see what the system believes.
    local_model_supports_vision: bool | None
    generalizer_model: str
    adjuster_model: str
    enricher_model: str
    normalizer_model: str
    validator_model: str
    # Which difficulty classifier is currently active for this workspace -
    # "legacy" (NVIDIA DeBERTa) or "labse" (LaBSE, the shipped default).
    classifier_choice: Literal["legacy", "labse"]
    enricher_system_prompt: str
    normalizer_system_prompt: str
    validator_system_prompt: str
    validator_image_system_prompt: str
    adjuster_system_prompt: str
    generalizer_system_prompt: str
    local_model_system_prompt: str
    routing_threshold: float
    # The legacy classifier's own threshold - kept separate from
    # routing_threshold (LaBSE's) since the two classifiers score on
    # different scales and must never share one cut.
    legacy_routing_threshold: float
    default_max_tokens: int
    rewrite_max_tokens: int
    ollama_num_ctx: int
    local_attachment_max_tokens: int
    # The shipped/global default for each token budget field, regardless of
    # whether this workspace overrides it - see LlmConfigResult in
    # llm_config_service.py for why the effective fields above can't serve
    # this on their own once an override is set.
    token_budget_defaults: dict[str, int]
    overrides: dict[str, str | float | int]
    updated_at: datetime | None
    is_default: bool
    credentials_configured: list[str]


class LlmConfigUpdate(BaseModel):
    external_model: str | None = None
    local_model: str | None = None
    generalizer_model: str | None = None
    adjuster_model: str | None = None
    enricher_model: str | None = None
    normalizer_model: str | None = None
    validator_model: str | None = None
    enricher_system_prompt: str | None = None
    normalizer_system_prompt: str | None = None
    validator_system_prompt: str | None = None
    validator_image_system_prompt: str | None = None
    adjuster_system_prompt: str | None = None
    generalizer_system_prompt: str | None = None
    local_model_system_prompt: str | None = None
    routing_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    classifier_choice: Literal["legacy", "labse"] | None = None
    legacy_routing_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    # Per-field bounds only - necessary but not sufficient. The relationship
    # between all three (rewrite must clear answer, context must clear
    # rewrite, and ollama_num_ctx's own ceiling) is enforced in
    # llm_config_service._validate_token_budget_overrides, which needs all
    # three values at once (or, for the ceiling, a value-specific error
    # message) and so cannot live in a single-field Pydantic validator - a
    # bare `le=` here would fail before that function ever runs and surface
    # only a generic "Input should be less than or equal to N", with no field
    # name and no reason, unlike every other rejection this feature raises.
    default_max_tokens: int | None = Field(default=None, gt=0)
    rewrite_max_tokens: int | None = Field(default=None, gt=0)
    ollama_num_ctx: int | None = Field(default=None, gt=0)
    # Ceiling on an attached file's extracted-text size (tokens) for local
    # answering - see LOCAL_ATTACHMENT_MAX_TOKENS in app/config.py. Bounds
    # attachment size, not generation length, so unlike the three fields
    # above it is not validated against them - only this per-field bound.
    # openai_compat.py still takes the smaller of this and the context
    # window at request time, so a value raised past what the context window
    # can hold is harmless, not rejected here.
    local_attachment_max_tokens: int | None = Field(default=None, gt=0)

    @field_validator(*PROMPT_FIELDS)
    @classmethod
    def _reject_empty_prompt(cls, value: str | None) -> str | None:
        # An admin who wants "no system prompt" for a role that structurally
        # requires one (e.g. the validator's one-word-verdict format) is very
        # likely to break it - force an explicit reset-to-null instead, which
        # restores the shipped default rather than sending an empty prompt.
        if value is not None and value.strip() == "":
            raise ValueError("Prompt cannot be empty - reset to null to use the shipped default.")
        return value

    @model_validator(mode="after")
    def _reject_empty_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one config field is required.")
        return self
