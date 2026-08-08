"""RAG (Rug) domain service: chunking, namespace helpers, index/retrieve.

The embedder and the Chroma collection are mocked — these tests exercise the
logic (chunk boundaries, deterministic ids, distance filtering), not the model or
the vector store.
"""
import pytest

from app.services import rag_service

pytestmark = pytest.mark.no_model


# --- namespace helpers --------------------------------------------------------

def test_rag_namespace_and_detection():
    assert rag_service.rag_namespace("acme") == "acme__rag_kb"
    assert rag_service.is_rag_namespace("acme__rag_kb")
    assert not rag_service.is_rag_namespace("acme__eng")
    assert not rag_service.is_rag_namespace("acme--default")


def test_rag_namespace_cannot_collide_with_a_department_named_rag():
    # A department slug can never contain an underscore (slugify maps `_`→`-`),
    # so the "{ws}__{deptslug}" cache namespace of a department named "RAG"
    # ("acme__rag") must NOT be mistaken for the knowledge-base collection.
    assert rag_service.rag_namespace("acme") != "acme__rag"
    assert not rag_service.is_rag_namespace("acme__rag")


# --- chunking -----------------------------------------------------------------

def test_chunk_short_text_is_one_chunk():
    assert rag_service.chunk_text("just a little text") == ["just a little text"]


def test_chunk_empty_text_is_no_chunks():
    assert rag_service.chunk_text("   ") == []


def test_chunk_long_text_splits_with_overlap(monkeypatch):
    monkeypatch.setattr(rag_service, "RAG_CHUNK_CHARS", 100)
    monkeypatch.setattr(rag_service, "RAG_CHUNK_OVERLAP", 20)
    text = ". ".join(f"sentence number {i} here" for i in range(60))
    chunks = rag_service.chunk_text(text)
    assert len(chunks) > 1
    # Every chunk respects the window size (allowing the boundary search slack).
    assert all(len(c) <= 100 for c in chunks)
    # Reassembling the (overlapping) chunks covers the source content.
    assert "sentence number 0" in chunks[0]
    assert "sentence number 59" in chunks[-1]


# --- index / retrieve ---------------------------------------------------------

class _FakeCollection:
    def __init__(self):
        self.upserted = None
        self._count = 0

    def upsert(self, ids, embeddings, documents, metadatas):
        self.upserted = {"ids": ids, "documents": documents, "metadatas": metadatas}
        self._count = len(ids)

    def count(self):
        return self._count

    def query(self, query_embeddings, n_results, include):
        # Two candidates: one within, one beyond the caller's max_distance.
        return {
            "ids": [["7:0", "7:1"]],
            "documents": [["close chunk", "far chunk"]],
            "metadatas": [[
                {"rag_document_id": 7, "title": "Doc", "chunk_index": 0},
                {"rag_document_id": 7, "title": "Doc", "chunk_index": 1},
            ]],
            "distances": [[0.10, 0.90]],
        }

    def delete(self, where):
        self.deleted_where = where


@pytest.fixture
def fake_collection(monkeypatch):
    col = _FakeCollection()
    monkeypatch.setattr(rag_service, "get_rag_collection", lambda ns: col)
    monkeypatch.setattr(rag_service, "embed_text", lambda text: [0.0, 1.0, 0.0])
    return col


def test_index_document_uses_deterministic_ids(fake_collection):
    n = rag_service.index_document(
        "acme__rag", 7, ["a", "b", "c"],
        workspace_slug="acme", title="Doc", kind="text", source_ref=None,
    )
    assert n == 3
    assert fake_collection.upserted["ids"] == ["7:0", "7:1", "7:2"]
    assert fake_collection.upserted["metadatas"][0]["rag_document_id"] == 7


def test_index_empty_chunks_stores_nothing(fake_collection):
    assert rag_service.index_document(
        "acme__rag", 7, [], workspace_slug="acme", title="Doc", kind="text", source_ref=None,
    ) == 0
    assert fake_collection.upserted is None


def test_retrieve_filters_by_max_distance(fake_collection):
    fake_collection._count = 2  # non-empty so retrieve issues the query
    chunks = rag_service.retrieve("acme__rag", "query", top_k=4, max_distance=0.35)
    # Only the 0.10 candidate clears the 0.35 ceiling; the 0.90 one is dropped.
    assert len(chunks) == 1
    assert chunks[0].text == "close chunk"
    assert chunks[0].distance == pytest.approx(0.10)
    assert chunks[0].rag_document_id == 7


def test_retrieve_empty_collection_returns_nothing(monkeypatch):
    class _Empty(_FakeCollection):
        def count(self):
            return 0

    monkeypatch.setattr(rag_service, "get_rag_collection", lambda ns: _Empty())
    monkeypatch.setattr(rag_service, "embed_text", lambda text: [0.0])
    assert rag_service.retrieve("acme__rag", "q", top_k=4, max_distance=0.35) == []


def test_delete_document_chunks_targets_the_document(fake_collection):
    rag_service.delete_document_chunks("acme__rag", 7)
    assert fake_collection.deleted_where == {"rag_document_id": 7}
