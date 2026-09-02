from datetime import datetime

from pydantic import BaseModel, field_validator


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
    provider: str
    key_preview: str
    created_at: datetime
    updated_at: datetime


class CredentialDeleteResponse(BaseModel):
    deleted: bool
