from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class LlmConfigResponse(BaseModel):
    external_model: str
    local_model: str
    routing_threshold: float
    overrides: dict[str, str | float]
    updated_at: datetime | None
    is_default: bool


class LlmConfigUpdate(BaseModel):
    external_model: str | None = None
    local_model: str | None = None
    routing_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _reject_empty_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one config field is required.")
        return self
