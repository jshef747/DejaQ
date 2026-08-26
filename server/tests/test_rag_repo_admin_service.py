"""Repository import orchestration: grouping, per-file rows, re-import pruning.

The fetch is mocked (a fake tarball never leaves this process) and the vector
side reuses the same in-memory chunk store the other RAG service tests use, so
what is asserted here is only the orchestration: one row per file carrying the
group key, an unchanged re-import touching nothing new, a changed file replacing
only its own row, and a deleted file's row and chunks going away.
"""
import io
import tarfile

import pytest

from app.db import rag_document_repo, workspace_repo
from app.db.session import get_session
from app.services import rag_admin_service, rag_ingest, rag_service
from app.services.rag_admin_service import RagIngestError

pytestmark = pytest.mark.no_model

ROOT = "owner-repo-abc1234"
BODY = "This sentence exists only so the file clears the minimum-characters floor. "


@pytest.fixture
def workspace(isolated_org_db):
    with get_session() as session:
        ws = workspace_repo.create_workspace(session, "Acme")
        return ws.slug


@pytest.fixture
def mock_vectors(monkeypatch):
    """Chunk one document into one chunk per 40 chars, kept in a dict keyed
    like Chroma ("{doc_id}:{index}"), so a missing chunk is visible as a
    missing key rather than as a call that looks plausible."""
    store: dict[str, str] = {}
    monkeypatch.setattr(
        rag_service, "chunk_document",
        lambda text, source_ref=None: (
            [text[i:i + 40] for i in range(0, len(text), 40)] if text.strip() else []
        ),
    )
    monkeypatch.setattr(
        rag_service, "embed_chunks", lambda chunks, on_progress=None: [[0.5]] * len(chunks)
    )

    def _index(namespace, doc_id, chunks, **kw):
        for i, chunk in enumerate(chunks):
            store[f"{doc_id}:{i}"] = chunk
        return len(chunks)

    def _delete(namespace, doc_id):
        for key in [k for k in store if k.split(":")[0] == str(doc_id)]:
            del store[key]

    def _delete_tail(namespace, doc_id, keep_count):
        for key in [
            k for k in store
            if k.split(":")[0] == str(doc_id) and int(k.split(":")[1]) >= keep_count
        ]:
            del store[key]

    monkeypatch.setattr(rag_service, "index_document", _index)
    monkeypatch.setattr(rag_service, "delete_document_chunks", _delete)
    monkeypatch.setattr(rag_service, "delete_chunk_tail", _delete_tail)
    return store


def _serve(monkeypatch, files: dict[str, str]):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{ROOT}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(rag_ingest, "_fetch_repo_tarball", lambda ref: (buf.getvalue(), ""))


def _import(workspace, monkeypatch, files):
    """Run a full import synchronously (fast phase + the slow phase inline)."""
    _serve(monkeypatch, files)
    result = rag_admin_service.begin_repo(workspace, "owner/repo")
    for item, chunks in result.documents:
        rag_admin_service._embed_and_index(workspace, item.id, chunks)
    return result


REPO_V1 = {
    "README.md": BODY + "DejaQ caches answers. Install with pip install dejaq.",
    "docs/routing.md": BODY + "Hard queries route to the external provider.",
    "src/main.py": BODY + "def route(query):\n    return 'local'\n",
}


def test_import_writes_one_row_per_file_all_sharing_a_group_key(workspace, mock_vectors, monkeypatch):
    result = _import(workspace, monkeypatch, REPO_V1)
    assert result.group_key == "github:owner/repo"
    assert len(result.documents) == 3 and result.skipped_files == 0
    docs = rag_admin_service.list_documents(workspace)
    assert sorted(d.title for d in docs) == ["README.md", "docs/routing.md", "src/main.py"]
    assert {d.group_key for d in docs} == {"github:owner/repo"}
    assert all(d.status == "ready" and d.chunk_count > 0 for d in docs)
    # Every row's chunks are in the store under its own id.
    for doc in docs:
        assert any(k.startswith(f"{doc.id}:") for k in mock_vectors)


def test_reimporting_an_unchanged_repo_duplicates_nothing(workspace, mock_vectors, monkeypatch):
    first = _import(workspace, monkeypatch, REPO_V1)
    before = {d.id: d.chunk_count for d in rag_admin_service.list_documents(workspace)}
    second = _import(workspace, monkeypatch, REPO_V1)
    after = {d.id: d.chunk_count for d in rag_admin_service.list_documents(workspace)}
    assert after == before                       # same ids, same chunk counts
    assert len(after) == 3
    assert second.removed == 0
    assert {i.id for i, _ in second.documents} == {i.id for i, _ in first.documents}


def test_changing_one_file_replaces_only_that_files_chunks(workspace, mock_vectors, monkeypatch):
    _import(workspace, monkeypatch, REPO_V1)
    docs = {d.title: d for d in rag_admin_service.list_documents(workspace)}
    untouched_id = docs["src/main.py"].id
    untouched_chunks = {k: v for k, v in mock_vectors.items()
                        if k.split(":")[0] == str(untouched_id)}

    changed = dict(REPO_V1)
    changed["README.md"] = BODY + "DejaQ caches answers. Install with uv sync instead."
    result = _import(workspace, monkeypatch, changed)

    after = {d.title: d for d in rag_admin_service.list_documents(workspace)}
    assert sorted(after) == ["README.md", "docs/routing.md", "src/main.py"]   # still 3 rows
    assert result.removed == 1                                   # the old README row went
    assert after["README.md"].id != docs["README.md"].id         # new sha -> new row
    assert after["src/main.py"].id == untouched_id               # unchanged file untouched
    assert {k: v for k, v in mock_vectors.items()
            if k.split(":")[0] == str(untouched_id)} == untouched_chunks
    # The replaced README's chunks are gone, not orphaned.
    assert not [k for k in mock_vectors if k.split(":")[0] == str(docs["README.md"].id)]
    assert "uv sync" in " ".join(
        v for k, v in mock_vectors.items() if k.split(":")[0] == str(after["README.md"].id)
    )


def test_a_file_removed_from_the_repo_loses_its_row_and_chunks(workspace, mock_vectors, monkeypatch):
    _import(workspace, monkeypatch, REPO_V1)
    dropped_id = {d.title: d.id for d in rag_admin_service.list_documents(workspace)}["docs/routing.md"]

    smaller = {k: v for k, v in REPO_V1.items() if k != "docs/routing.md"}
    result = _import(workspace, monkeypatch, smaller)

    assert result.removed == 1
    titles = sorted(d.title for d in rag_admin_service.list_documents(workspace))
    assert titles == ["README.md", "src/main.py"]
    assert not [k for k in mock_vectors if k.split(":")[0] == str(dropped_id)]


def test_pruning_only_touches_this_repos_group(workspace, mock_vectors, monkeypatch):
    """A pasted document (no group key) and another repo's rows must survive a
    re-import that removes files from THIS repo."""
    pasted = rag_admin_service.add_text(workspace, "Refunds", BODY + "Refunds within 30 days.")
    _import(workspace, monkeypatch, REPO_V1)
    _import(workspace, monkeypatch, {"README.md": REPO_V1["README.md"]})

    docs = {d.title: d for d in rag_admin_service.list_documents(workspace)}
    assert "Refunds" in docs and docs["Refunds"].id == pasted.id
    assert docs["Refunds"].group_key is None
    assert sorted(t for t in docs if t != "Refunds") == ["README.md"]


def test_import_refuses_a_repo_with_nothing_indexable(workspace, mock_vectors, monkeypatch):
    _serve(monkeypatch, {"logo.png": "not really a png but the extension is filtered"})
    with pytest.raises(RagIngestError, match="no indexable text"):
        rag_admin_service.begin_repo(workspace, "owner/repo")


def test_import_surfaces_a_private_repository_message(workspace, monkeypatch):
    monkeypatch.setattr(
        rag_ingest, "_fetch_repo_tarball",
        lambda ref: (b"", "GitHub has no public repository 'owner/repo'. ... private "
                          "repositories are not supported"),
    )
    with pytest.raises(RagIngestError, match="private repositories are not supported"):
        rag_admin_service.begin_repo(workspace, "owner/repo")


def test_deleting_a_repo_document_clears_its_chunks(workspace, mock_vectors, monkeypatch):
    _import(workspace, monkeypatch, REPO_V1)
    doc = rag_admin_service.list_documents(workspace)[0]
    rag_admin_service.delete_document(workspace, doc.id)
    assert not [k for k in mock_vectors if k.split(":")[0] == str(doc.id)]
    assert doc.id not in {d.id for d in rag_admin_service.list_documents(workspace)}


def test_group_key_is_queryable_for_the_dashboard(workspace, mock_vectors, monkeypatch):
    _import(workspace, monkeypatch, REPO_V1)
    with get_session() as session:
        ws_id = session.query(workspace_repo.Workspace).filter_by(slug=workspace).first().id
        rows = rag_document_repo.list_for_group(session, ws_id, "github:owner/repo")
        assert len(rows) == 3
        assert rag_document_repo.list_for_group(session, ws_id, "github:other/repo") == []
