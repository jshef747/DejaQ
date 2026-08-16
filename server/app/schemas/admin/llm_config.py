from datetime import datetime

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
    external_model: str
    local_model: str
    generalizer_model: str
    adjuster_model: str
    enricher_model: str
    normalizer_model: str
    validator_model: str
    enricher_system_prompt: str
    normalizer_system_prompt: str
    validator_system_prompt: str
    validator_image_system_prompt: str
    adjuster_system_prompt: str
    generalizer_system_prompt: str
    local_model_system_prompt: str
    routing_threshold: float
    default_max_tokens: int
    rewrite_max_tokens: int
    ollama_num_ctx: int
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
    # Per-field bounds only - necessary but not sufficient. The relationship
    # between all three (rewrite must clear answer, context must clear
    # rewrite) is enforced in llm_config_service._validate_token_budget_overrides,
    # which needs all three values at once and so cannot live in a single-field
    # Pydantic validator.
    default_max_tokens: int | None = Field(default=None, gt=0)
    rewrite_max_tokens: int | None = Field(default=None, gt=0)
    ollama_num_ctx: int | None = Field(default=None, gt=0)

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
