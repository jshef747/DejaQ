"""RAG (Rug) admin orchestration: catalog + vector coordination + access control.

Uses the isolated SQLite DB fixture. rag_service (the Chroma/embedder side) is
mocked so the tests stay offline; what is asserted is the orchestration: a catalog
row is written, chunks are indexed under the row id, re-adding identical content
replaces rather than duplicates, delete removes both sides, and a user actor
without access is refused.
"""
import pytest

from app.db import rag_document_repo, workspace_repo
from app.db.session import get_session
from app.dependencies.management_auth import ManagementAuthContext
from app.services import rag_admin_service, rag_service
from app.services.admin_service import WorkspaceForbidden, WorkspaceNotFound

pytestmark = pytest.mark.no_model

_SYSTEM = ManagementAuthContext.system()


@pytest.fixture
def workspace(isolated_org_db):
    with get_session() as session:
        ws = workspace_repo.create_workspace(session, "Acme")
        slug = ws.slug
    return slug


@pytest.fixture
def mock_vectors(monkeypatch):
    """Replace the vector side: chunk into fixed pieces, record index/delete calls."""
    calls = {"indexed": [], "deleted": []}
    monkeypatch.setattr(rag_service, "chunk_text", lambda text: ["chunk-a", "chunk-b"])

    def _index(namespace, doc_id, chunks, **kw):
        calls["indexed"].append((namespace, doc_id, len(chunks)))
        return len(chunks)

    monkeypatch.setattr(rag_service, "index_document", _index)
    monkeypatch.setattr(
        rag_service, "delete_document_chunks",
        lambda ns, doc_id: calls["deleted"].append((ns, doc_id)),
    )
    return calls


def test_add_text_writes_catalog_row_and_indexes(workspace, mock_vectors):
    item = rag_admin_service.add_text(workspace, "Policy", "Refunds within 30 days.", _SYSTEM)
    assert item.kind == "text" and item.chunk_count == 2
    # A catalog row exists.
    docs = rag_admin_service.list_documents(workspace, _SYSTEM)
    assert [d.id for d in docs] == [item.id]
    # Chunks were indexed under this document id, in the workspace RAG namespace.
    ns = rag_service.rag_namespace(workspace)
    assert mock_vectors["indexed"] == [(ns, item.id, 2)]


def test_re_adding_identical_content_replaces_not_duplicates(workspace, mock_vectors):
    first = rag_admin_service.add_text(workspace, "Policy", "Same body.", _SYSTEM)
    second = rag_admin_service.add_text(workspace, "Policy renamed", "Same body.", _SYSTEM)
    docs = rag_admin_service.list_documents(workspace, _SYSTEM)
    assert len(docs) == 1  # replaced, not duplicated
    # The old document's chunks were deleted before the new ones were indexed.
    ns = rag_service.rag_namespace(workspace)
    assert (ns, first.id) in mock_vectors["deleted"]
    assert second.id != first.id or docs[0].title == "Policy renamed"


def test_delete_removes_catalog_row_and_chunks(workspace, mock_vectors):
    item = rag_admin_service.add_text(workspace, "Policy", "Body.", _SYSTEM)
    assert rag_admin_service.delete_document(workspace, item.id, _SYSTEM) is True
    assert rag_admin_service.list_documents(workspace, _SYSTEM) == []
    ns = rag_service.rag_namespace(workspace)
    assert (ns, item.id) in mock_vectors["deleted"]


def test_delete_missing_document_raises(workspace, mock_vectors):
    with pytest.raises(rag_admin_service.RagDocumentNotFound):
        rag_admin_service.delete_document(workspace, 9999, _SYSTEM)


def test_unknown_workspace_raises(mock_vectors, isolated_org_db):
    with pytest.raises(WorkspaceNotFound):
        rag_admin_service.list_documents("nope", _SYSTEM)


def test_user_without_access_is_forbidden(workspace, mock_vectors):
    # A user actor whose accessible_workspaces does not include this workspace.
    stranger = ManagementAuthContext(actor_type="user", local_user_id=42, accessible_workspaces=[])
    with pytest.raises(WorkspaceForbidden):
        rag_admin_service.add_text(workspace, "Policy", "Body.", stranger)


def test_access_is_checked_before_ingest_runs(workspace, mock_vectors, monkeypatch):
    """A caller without access must be denied BEFORE any URL fetch / extraction —
    the server must not be made to fetch a URL on an unauthorized user's behalf."""
    def _boom(*a, **k):
        raise AssertionError("ingestion must not run before the access check")

    monkeypatch.setattr(rag_admin_service.rag_ingest, "from_url", _boom)
    stranger = ManagementAuthContext(actor_type="user", local_user_id=42, accessible_workspaces=[])
    with pytest.raises(WorkspaceForbidden):
        rag_admin_service.add_url(workspace, "https://example.com", None, stranger)


def test_ingest_failure_surfaces_as_rag_ingest_error(workspace, mock_vectors):
    with pytest.raises(rag_admin_service.RagIngestError):
        rag_admin_service.add_text(workspace, "Empty", "   ", _SYSTEM)


def test_repo_dedupe_by_sha_is_enforced(workspace):
    # Direct repo check: two rows with the same (workspace_id, sha) cannot coexist.
    from sqlalchemy.exc import IntegrityError

    from app.db.models.workspace import Workspace

    with get_session() as session:
        ws_id = session.query(Workspace).filter_by(slug=workspace).first().id
        rag_document_repo.create(
            session, ws_id, title="A", kind="text", source="paste",
            source_ref=None, sha="deadbeef", char_count=10, chunk_count=1,
        )
    with pytest.raises(IntegrityError):
        with get_session() as session:
            rag_document_repo.create(
                session, ws_id, title="B", kind="text", source="paste",
                source_ref=None, sha="deadbeef", char_count=10, chunk_count=1,
            )
