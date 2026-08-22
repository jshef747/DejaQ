"""RAG admin orchestration: catalog + vector coordination.

Uses the isolated SQLite DB fixture. rag_service (the Chroma/embedder side) is
mocked so the tests stay offline; what is asserted is the orchestration: a catalog
row is written, chunks are indexed under the row id, re-adding identical content
replaces rather than duplicates, delete removes both sides, and an unknown
workspace is refused.
"""
import pytest

from app.db import rag_document_repo, workspace_repo
from app.db.session import get_session
from app.services import rag_admin_service, rag_service
from app.services.admin_service import WorkspaceNotFound

pytestmark = pytest.mark.no_model


@pytest.fixture
def workspace(isolated_org_db):
    with get_session() as session:
        ws = workspace_repo.create_workspace(session, "Acme")
        slug = ws.slug
    return slug


@pytest.fixture
def mock_vectors(monkeypatch):
    """Replace the vector side with an in-memory chunk store.

    `store` is keyed exactly like Chroma ("{doc_id}:{index}"), so a delete that
    targets the ids just written shows up as missing chunks rather than as a
    plausible-looking call log.
    """
    calls = {"indexed": [], "deleted": [], "order": [], "embeddings": [], "store": {}}
    store = calls["store"]
    monkeypatch.setattr(rag_service, "chunk_text", lambda text: ["chunk-a", "chunk-b"])
    monkeypatch.setattr(rag_service, "embed_chunks", lambda chunks: [[0.5]] * len(chunks))

    def _index(namespace, doc_id, chunks, **kw):
        for i, chunk in enumerate(chunks):
            store[f"{doc_id}:{i}"] = chunk
        calls["indexed"].append((namespace, doc_id, len(chunks)))
        calls["embeddings"].append(kw.get("embeddings"))
        calls["order"].append(("index", doc_id))
        return len(chunks)

    def _delete(namespace, doc_id):
        for key in [k for k in store if k.split(":")[0] == str(doc_id)]:
            del store[key]
        calls["deleted"].append((namespace, doc_id))
        calls["order"].append(("delete", doc_id))

    def _delete_tail(namespace, doc_id, keep_count):
        for key in [
            k for k in store
            if k.split(":")[0] == str(doc_id) and int(k.split(":")[1]) >= keep_count
        ]:
            del store[key]
        calls["order"].append(("delete_tail", doc_id, keep_count))

    monkeypatch.setattr(rag_service, "index_document", _index)
    monkeypatch.setattr(rag_service, "delete_document_chunks", _delete)
    monkeypatch.setattr(rag_service, "delete_chunk_tail", _delete_tail)
    return calls


def test_add_text_writes_catalog_row_and_indexes(workspace, mock_vectors):
    item = rag_admin_service.add_text(workspace, "Policy", "Refunds within 30 days.")
    assert item.kind == "text" and item.chunk_count == 2
    # A catalog row exists.
    docs = rag_admin_service.list_documents(workspace)
    assert [d.id for d in docs] == [item.id]
    # Chunks were indexed under this document id, in the workspace RAG namespace.
    ns = rag_service.rag_namespace(workspace)
    assert mock_vectors["indexed"] == [(ns, item.id, 2)]


def test_add_text_embeds_once_and_passes_the_vectors_to_the_index(workspace, mock_vectors):
    rag_admin_service.add_text(workspace, "Policy", "Refunds within 30 days.")
    # Vectors are computed up front (outside the write transaction) and handed in,
    # so index_document never re-embeds while holding the SQLite write lock.
    assert mock_vectors["embeddings"] == [[[0.5], [0.5]]]


def test_re_adding_identical_content_replaces_not_duplicates(workspace, mock_vectors):
    first = rag_admin_service.add_text(workspace, "Policy", "Same body.")
    second = rag_admin_service.add_text(workspace, "Policy renamed", "Same body.")
    docs = rag_admin_service.list_documents(workspace)
    assert len(docs) == 1  # replaced, not duplicated
    assert docs[0].title == "Policy renamed"
    # The row is refreshed in place, so the id chunks are keyed by never moves.
    assert second.id == first.id
    assert mock_vectors["deleted"] == []


def test_re_adding_keeps_the_chunks_it_just_wrote(workspace, mock_vectors):
    """The replaced document must still be retrievable afterwards.

    SQLite reuses a deleted rowid, so a replace that dropped the old row and
    inserted a new one could be handed the same id — and a delete-by-document-id
    cleanup would then wipe the chunks the re-index had just written, leaving a
    catalog row that grounds nothing and no error anywhere.
    """
    first = rag_admin_service.add_text(workspace, "Policy", "Same body.")
    second = rag_admin_service.add_text(workspace, "Policy renamed", "Same body.")
    assert second.chunk_count == 2
    assert first.id == second.id
    assert mock_vectors["store"] == {f"{second.id}:0": "chunk-a", f"{second.id}:1": "chunk-b"}


def test_a_shorter_rewrite_drops_only_the_stale_tail(workspace, mock_vectors, monkeypatch):
    first = rag_admin_service.add_text(workspace, "Policy", "Same body.")
    assert len(mock_vectors["store"]) == 2

    # Same sha (sha is over the NORMALISED text) but a shorter chunking, so the
    # previous version's last chunk is no longer part of the document.
    monkeypatch.setattr(rag_service, "chunk_text", lambda text: ["chunk-a"])
    second = rag_admin_service.add_text(workspace, "Policy", "Same  body.")

    assert second.id == first.id and second.chunk_count == 1
    assert mock_vectors["store"] == {f"{second.id}:0": "chunk-a"}
    assert ("delete_tail", second.id, 1) in mock_vectors["order"]


def test_failed_reindex_leaves_the_previous_document_intact(workspace, mock_vectors, monkeypatch):
    first = rag_admin_service.add_text(workspace, "Policy", "Same body.")
    chunks_before = dict(mock_vectors["store"])

    def _boom(*a, **kw):
        raise RuntimeError("chroma down")

    monkeypatch.setattr(rag_service, "index_document", _boom)
    with pytest.raises(RuntimeError):
        rag_admin_service.add_text(workspace, "Policy renamed", "Same body.")

    # The catalog row survived the rollback with its original title, and its
    # chunks were never deleted — the document grounds answers as it did before.
    docs = rag_admin_service.list_documents(workspace)
    assert [(d.id, d.title) for d in docs] == [(first.id, "Policy")]
    assert mock_vectors["deleted"] == []
    assert mock_vectors["store"] == chunks_before


def test_delete_removes_catalog_row_and_chunks(workspace, mock_vectors):
    item = rag_admin_service.add_text(workspace, "Policy", "Body.")
    assert rag_admin_service.delete_document(workspace, item.id) is True
    assert rag_admin_service.list_documents(workspace) == []
    ns = rag_service.rag_namespace(workspace)
    assert (ns, item.id) in mock_vectors["deleted"]


def test_failed_chunk_delete_keeps_the_catalog_row(workspace, mock_vectors, monkeypatch):
    # A Chroma failure must fail the request and leave the row, never report
    # deleted=true while orphaned chunks keep grounding answers.
    item = rag_admin_service.add_text(workspace, "Policy", "Body.")

    def _boom(ns, doc_id):
        raise RuntimeError("chroma down")

    monkeypatch.setattr(rag_service, "delete_document_chunks", _boom)
    with pytest.raises(RuntimeError):
        rag_admin_service.delete_document(workspace, item.id)
    assert [d.id for d in rag_admin_service.list_documents(workspace)] == [item.id]


def test_delete_missing_document_raises(workspace, mock_vectors):
    with pytest.raises(rag_admin_service.RagDocumentNotFound):
        rag_admin_service.delete_document(workspace, 9999)


def test_unknown_workspace_raises(mock_vectors, isolated_org_db):
    with pytest.raises(WorkspaceNotFound):
        rag_admin_service.list_documents("nope")


def test_every_add_path_is_refused_when_rag_is_disabled(workspace, mock_vectors, monkeypatch):
    """DEJAQ_RAG_ENABLED=false must stop knowledge from accumulating anywhere.

    Retrieval never runs with the switch off, so an add that still indexed would
    silently grow a knowledge base that grounds nothing. The gate sits on the
    service, which the HTTP router and the `dejaq-admin rag` CLI both go through.
    """
    monkeypatch.setattr(rag_admin_service, "RAG_ENABLED", False)

    def _boom(*a, **k):
        raise AssertionError("ingestion must not run when RAG is disabled")

    monkeypatch.setattr(rag_admin_service.rag_ingest, "from_url", _boom)
    monkeypatch.setattr(rag_admin_service.rag_ingest, "from_upload", _boom)

    with pytest.raises(rag_admin_service.RagDisabledError):
        rag_admin_service.add_text(workspace, "Policy", "Body.")
    with pytest.raises(rag_admin_service.RagDisabledError):
        rag_admin_service.add_url(workspace, "https://example.com", None)
    with pytest.raises(rag_admin_service.RagDisabledError):
        rag_admin_service.add_upload(workspace, "a.md", b"# hi", "text/markdown", None)

    assert rag_admin_service.list_documents(workspace) == []
    assert mock_vectors["indexed"] == []


def test_listing_and_deleting_still_work_when_rag_is_disabled(workspace, mock_vectors, monkeypatch):
    # Turning the switch off must not strand existing knowledge: an operator can
    # still see it and clean it up.
    item = rag_admin_service.add_text(workspace, "Policy", "Body.")
    monkeypatch.setattr(rag_admin_service, "RAG_ENABLED", False)
    assert [d.id for d in rag_admin_service.list_documents(workspace)] == [item.id]
    assert rag_admin_service.delete_document(workspace, item.id) is True


def test_ingest_failure_surfaces_as_rag_ingest_error(workspace, mock_vectors):
    with pytest.raises(rag_admin_service.RagIngestError):
        rag_admin_service.add_text(workspace, "Empty", "   ")


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
