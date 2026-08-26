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
    # Non-null only for rows imported together as one unit (a GitHub
    # repository): the dashboard collapses a shared group_key into one entry.
    group_key: str | None = None
    char_count: int
    byte_size: int
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


class RagRepoCreate(BaseModel):
    """Import a public GitHub repository.

    `url` accepts what people paste: "owner/repo", "github.com/owner/repo", the
    full https URL, or a /tree/<branch> deep link. `ref` (branch, tag, or sha)
    overrides any ref in the URL; omit both for the default branch.
    """

    url: str
    ref: str | None = None

    @field_validator("url")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("repository URL must not be empty")
        return stripped


class RagRepoImportResponse(BaseModel):
    """The 202 body for a repository import.

    Unlike the single-document routes this returns MANY rows - one per file -
    plus the counts an operator needs to trust the result: how many files the
    filter dropped, and how many rows from a previous import of the same repo
    were removed because their content is no longer in it.
    """

    repo: str
    ref: str
    group_key: str
    documents: list[RagDocumentItem]
    indexed_files: int
    skipped_files: int
    removed_documents: int


class RagDocumentDeleteResponse(BaseModel):
    id: int
    deleted: bool
