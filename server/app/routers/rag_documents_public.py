import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import RAG_ENABLED, RAG_SUGGEST_ENABLED, RAG_SUGGEST_MAX_DISTANCE
from app.db import rag_document_repo
from app.db.session import get_session
from app.dependencies.auth import ResolvedWorkspace, require_org_key
from app.services import rag_service

logger = logging.getLogger("dejaq.router.rag_documents_public")

router = APIRouter()

# Below this many characters, a partial word is noise, not a question — no
# point paying an embedding call for it. Not configurable: this floor isn't a
# recall/precision dial like RAG_SUGGEST_MAX_DISTANCE, just a cheap short-circuit.
_SUGGEST_MIN_QUERY_CHARS = 3
_SUGGEST_SNIPPET_CHARS = 160


class RagDocumentPickerItem(BaseModel):
    id: int
    title: str
    kind: str
    # Set on documents imported as part of one group — today only a GitHub
    # repository ("github:{owner}/{repo}"), one row per file. The picker
    # collapses a shared key into one expandable repository entry, and
    # referencing that entry sends `rag_group_key` instead of an id. Null for
    # every other source. Same field, same meaning, as the dashboard's.
    group_key: str | None = None


@router.get("/rag-documents", response_model=list[RagDocumentPickerItem])
def list_rag_documents(
    workspace: ResolvedWorkspace = Depends(require_org_key),
) -> list[RagDocumentPickerItem]:
    """List the workspace's knowledge-base documents for the chat app's `@`
    picker. Mirrors GET /departments exactly (same auth dependency, same
    shape): the admin catalog lives behind loopback-only /admin/v1/*, and the
    chat app has no other way to see what documents exist.

    Only what a picker needs — id, title, kind, group_key — never document
    content.
    """
    # Built INSIDE the session block: get_session() commits on exit, which
    # expires every loaded attribute (SQLAlchemy's expire_on_commit default),
    # and the session is closed by the time the `with` exits — reading a
    # column off `d` afterwards is a detached-instance error, not a cache hit.
    with get_session() as session:
        docs = rag_document_repo.list_for_workspace(session, workspace.workspace_id)
        items = [
            RagDocumentPickerItem(id=d.id, title=d.title, kind=d.kind, group_key=d.group_key)
            for d in docs
        ]

    logger.info("GET /rag-documents workspace=%s count=%d", workspace.workspace_slug, len(items))
    return items


class RagSuggestRequest(BaseModel):
    query: str


class RagSuggestion(BaseModel):
    """A visible, dismissible guess at which document a question is about.

    Never grounds anything by itself — document_id is null (every other field
    absent) when there is no suggestion. Accepting one in the chat app sets an
    ordinary explicit `@`-reference (rag_document_id), the same state the `@`
    picker sets; nothing here talks to the answer-generation pipeline.
    """
    document_id: int | None = None
    title: str | None = None
    snippet: str | None = None
    distance: float | None = None


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= _SUGGEST_SNIPPET_CHARS:
        return flat
    return flat[:_SUGGEST_SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"


@router.post("/rag-suggest", response_model=RagSuggestion)
def suggest_rag_document(
    body: RagSuggestRequest,
    workspace: ResolvedWorkspace = Depends(require_org_key),
) -> RagSuggestion:
    """"This might be about {doc}" for the chat composer — debounced, called
    while the user is still typing, well before send.

    Reuses `rag_service.retrieve()` completely unchanged: the same
    exhaustive/ANN self-tuning the (now-removed) automatic-grounding path
    relied on, just top_k=1 (only the single best guess is worth naming) and
    a looser distance ceiling (RAG_SUGGEST_MAX_DISTANCE) than grounding ever
    used — offering a wrong guess costs a glance and a dismiss, not a
    misleading answer. See docs/rag-layer.md and
    firstmate/data/dejaq-rag-suggest/report.md for the measured tradeoff.

    Gated on BOTH RAG_ENABLED (the layer's master switch — off means no
    knowledge base at all, uploads included) and RAG_SUGGEST_ENABLED (this
    feature's own switch, independent of the removed auto-retrieve flag).
    Either off, or a too-short query, returns no suggestion rather than an
    error — the composer has nothing to show, not something to apologise for.
    """
    query = body.query.strip()
    if not RAG_ENABLED or not RAG_SUGGEST_ENABLED or len(query) < _SUGGEST_MIN_QUERY_CHARS:
        return RagSuggestion()

    namespace = rag_service.rag_namespace(workspace.workspace_slug)
    chunks = rag_service.retrieve(namespace, query, 1, RAG_SUGGEST_MAX_DISTANCE)
    if not chunks:
        logger.info("POST /rag-suggest workspace=%s suggested=false", workspace.workspace_slug)
        return RagSuggestion()

    top = chunks[0]
    logger.info(
        "POST /rag-suggest workspace=%s suggested=true doc_id=%d distance=%.4f",
        workspace.workspace_slug, top.rag_document_id, top.distance,
    )
    return RagSuggestion(
        document_id=top.rag_document_id,
        title=top.title,
        snippet=_snippet(top.text),
        distance=top.distance,
    )
