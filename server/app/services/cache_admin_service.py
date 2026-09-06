"""Read/edit/delete cache entries for the dashboard Cache browser.

Deliberately does not go through `get_memory_service()` for listing: that call
`get_or_create_collection`s, so viewing an empty department would create a
Chroma collection just because an operator looked at it. This module opens a
raw `chromadb.HttpClient` and checks `list_collections()` first — a missing
collection is `total: 0`, never created.

Edit and delete run against an entry that must already exist, so the
collection must already exist too; those paths still check existence first
(same client) before touching `get_memory_service()`'s pooled instance, so a
bogus entry id against a namespace with no collection 404s instead of quietly
creating one.
"""

from __future__ import annotations

import logging

import chromadb

from app.config import CHROMA_HOST, CHROMA_PORT
from app.services import admin_service
from app.services.admin_service import DeptNotFound, WorkspaceNotFound  # noqa: F401 (re-exported)
from app.services.answer_edit import validate_edited_answer
from app.services.memory_chromaDB import get_memory_service
from app.schemas.admin.cache_entries import (
    CacheEntryDeleteResult,
    CacheEntryEditResult,
    CacheEntryItem,
    CacheEntryPage,
)

logger = logging.getLogger("dejaq.services.cache_admin_service")

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
QUERY_PREVIEW_CHARS = 400
ANSWER_PREVIEW_CHARS = 3000

_IMAGE_META_KEYS = ("image_kind", "image_dhash", "image_clip", "image_text")


class CacheEntryNotFound(Exception):
    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id
        super().__init__(f"Cache entry '{entry_id}' not found.")


class ChromaUnavailable(Exception):
    """Chroma could not be reached. Message is generic on purpose — no internals leak to the browser."""


def _resolve_department(workspace_slug: str, dept_slug: str) -> admin_service.DepartmentItem:
    depts = admin_service.list_departments(workspace_slug)  # raises WorkspaceNotFound
    for dept in depts:
        if dept.slug == dept_slug:
            return dept
    raise DeptNotFound(workspace_slug, dept_slug)


def _chroma_client() -> chromadb.HttpClient:
    try:
        return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    except Exception as exc:
        logger.error("Could not reach ChromaDB", exc_info=True)
        raise ChromaUnavailable("cache storage is temporarily unavailable") from exc


def _collection_exists(client: chromadb.HttpClient, namespace: str) -> bool:
    try:
        existing = [c if isinstance(c, str) else c.name for c in client.list_collections()]
    except Exception as exc:
        logger.error("Could not list ChromaDB collections", exc_info=True)
        raise ChromaUnavailable("cache storage is temporarily unavailable") from exc
    return namespace in existing


def _truncate(text: str | None, limit: int) -> tuple[str, bool]:
    text = text or ""
    if len(text) > limit:
        return text[:limit], True
    return text, False


def _kind_for(meta: dict) -> str:
    if meta.get("alias_of"):
        return "alias"
    if meta.get("authored") == "human":
        return "human"
    if any(meta.get(key) for key in _IMAGE_META_KEYS):
        return "image"
    if meta.get("file_sha"):
        return "file"
    if meta.get("rag_document_id") is not None or meta.get("rag_document_ids"):
        return "rag"
    return "text"


def _rag_document_ids(meta: dict) -> list[str]:
    raw = meta.get("rag_document_ids")
    if raw:
        return [part for part in str(raw).split(",") if part]
    single = meta.get("rag_document_id")
    if single is not None:
        return [str(single)]
    return []


def _entry_item(doc_id: str, document: str, meta: dict) -> CacheEntryItem:
    original, original_truncated = _truncate(meta.get("original_query", ""), QUERY_PREVIEW_CHARS)
    normalized, normalized_truncated = _truncate(document, QUERY_PREVIEW_CHARS)
    answer, answer_truncated = _truncate(meta.get("generalized_answer", ""), ANSWER_PREVIEW_CHARS)
    return CacheEntryItem(
        id=doc_id,
        kind=_kind_for(meta),
        is_alias=bool(meta.get("alias_of")),
        original_query_preview=original,
        normalized_query_preview=normalized,
        answer_preview=answer,
        text_truncated=original_truncated or normalized_truncated or answer_truncated,
        stored_at=meta.get("stored_at", ""),
        score=float(meta.get("score", 0.0) or 0.0),
        hit_count=int(meta.get("hit_count", 0) or 0),
        negative_count=int(meta.get("negative_count", 0) or 0),
        authored=meta.get("authored"),
        alias_of=meta.get("alias_of"),
        attachment_kind=meta.get("image_kind"),
        file_kind=meta.get("file_kind"),
        rag_document_ids=_rag_document_ids(meta),
    )


def list_cache_entries(
    workspace_slug: str,
    dept_slug: str,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> CacheEntryPage:
    dept = _resolve_department(workspace_slug, dept_slug)
    client = _chroma_client()

    empty_page = CacheEntryPage(
        workspace=workspace_slug,
        department=dept_slug,
        department_name=dept.name,
        cache_namespace=dept.cache_namespace,
        total=0,
        limit=limit,
        offset=offset,
        items=[],
    )
    if not _collection_exists(client, dept.cache_namespace):
        return empty_page

    try:
        collection = client.get_collection(dept.cache_namespace)
        total = collection.count()
        results = collection.get(include=["documents", "metadatas"], limit=limit, offset=offset)
    except Exception as exc:
        logger.error("Could not read ChromaDB collection '%s'", dept.cache_namespace, exc_info=True)
        raise ChromaUnavailable("cache storage is temporarily unavailable") from exc

    items = [
        _entry_item(
            doc_id,
            results["documents"][i] if results.get("documents") else "",
            (results["metadatas"][i] if results.get("metadatas") else {}) or {},
        )
        for i, doc_id in enumerate(results.get("ids", []))
    ]
    return CacheEntryPage(
        workspace=workspace_slug,
        department=dept_slug,
        department_name=dept.name,
        cache_namespace=dept.cache_namespace,
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


def edit_cache_entry_answer(
    workspace_slug: str,
    dept_slug: str,
    entry_id: str,
    answer: str,
) -> CacheEntryEditResult:
    validate_edited_answer(answer)  # raises ValueError on empty/oversized
    dept = _resolve_department(workspace_slug, dept_slug)
    client = _chroma_client()
    if not _collection_exists(client, dept.cache_namespace):
        raise CacheEntryNotFound(entry_id)

    try:
        root_id = get_memory_service(dept.cache_namespace).overwrite_answer(
            entry_id, answer, authored="human"
        )
    except KeyError:
        raise CacheEntryNotFound(entry_id)
    return CacheEntryEditResult(id=root_id, redirected=root_id != entry_id)


def delete_cache_entry(
    workspace_slug: str,
    dept_slug: str,
    entry_id: str,
) -> CacheEntryDeleteResult:
    dept = _resolve_department(workspace_slug, dept_slug)
    client = _chroma_client()
    if not _collection_exists(client, dept.cache_namespace):
        raise CacheEntryNotFound(entry_id)

    deleted = get_memory_service(dept.cache_namespace).delete_entry(entry_id)
    if not deleted:
        raise CacheEntryNotFound(entry_id)
    return CacheEntryDeleteResult(id=entry_id, deleted=True)
