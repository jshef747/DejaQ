from pydantic import BaseModel


class CacheEntryItem(BaseModel):
    """One cache entry as shown in the dashboard Cache browser.

    Deliberately excludes user_id, embeddings, image_clip/image_dhash, full
    file_sha, and hidden/system prompts — see docs/openai-compat-api.md and
    CLAUDE.md's cache-entries privacy limits.
    """

    id: str
    kind: str
    is_alias: bool
    original_query_preview: str
    normalized_query_preview: str
    answer_preview: str
    text_truncated: bool
    stored_at: str
    score: float
    hit_count: int
    negative_count: int
    authored: str | None = None
    alias_of: str | None = None
    attachment_kind: str | None = None
    file_kind: str | None = None
    rag_document_ids: list[str] = []


class CacheEntryPage(BaseModel):
    workspace: str
    department: str
    department_name: str
    cache_namespace: str
    total: int
    limit: int
    offset: int
    items: list[CacheEntryItem]


class CacheAnswerEdit(BaseModel):
    answer: str


class CacheEntryEditResult(BaseModel):
    id: str
    redirected: bool


class CacheEntryDeleteResult(BaseModel):
    id: str
    deleted: bool
