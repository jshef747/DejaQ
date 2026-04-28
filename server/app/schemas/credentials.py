from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, field_validator


class ProviderEnum(StrEnum):
    google = "google"
    openai = "openai"
    anthropic = "anthropic"
    mistral = "mistral"
    cohere = "cohere"
    together = "together"
    groq = "groq"
    fireworks = "fireworks"


class CredentialUpsertRequest(BaseModel):
    api_key: str

    @field_validator("api_key")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("API key must not be empty.")
        return stripped


class CredentialResponse(BaseModel):
    provider: ProviderEnum
    key_preview: str
    created_at: datetime
    updated_at: datetime


class CredentialDeleteResponse(BaseModel):
    deleted: bool
