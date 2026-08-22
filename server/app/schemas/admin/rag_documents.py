from datetime import datetime

from pydantic import BaseModel, field_validator


class RagDocumentItem(BaseModel):
    """One knowledge-base document as shown in the dashboard list."""

    model_config = {"from_attributes": True}

    id: int
    title: str
    kind: str
    source: str
    source_ref: str | None
    char_count: int
    chunk_count: int
    status: str
    progress_current: int
    progress_total: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class RagTextCreate(BaseModel):
    title: str
    content: str

    @field_validator("title", "content")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return value


class RagUrlCreate(BaseModel):
    url: str
    title: str | None = None

    @field_validator("url")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("URL must not be empty")
        return stripped


class RagDocumentDeleteResponse(BaseModel):
    id: int
    deleted: bool
