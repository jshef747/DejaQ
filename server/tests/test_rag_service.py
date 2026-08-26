"""RAG domain service: chunking, namespace helpers, index/retrieve.

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


# --- embedding progress --------------------------------------------------------

def test_embed_chunks_reports_progress_after_every_chunk(monkeypatch):
    monkeypatch.setattr(rag_service, "embed_text", lambda text: [len(text)])
    seen = []
    embeddings = rag_service.embed_chunks(["a", "bb", "ccc"], on_progress=seen.append)
    assert embeddings == [[1], [2], [3]]
    assert seen == [1, 2, 3]  # count embedded so far, not a chunk index


# --- index / retrieve ---------------------------------------------------------

class _FakeCollection:
    def __init__(self):
        self.upserted = None
        self.upsert_calls = []
        self._count = 0

    def upsert(self, ids, embeddings, documents, metadatas):
        self.upserted = {"ids": ids, "documents": documents, "metadatas": metadatas}
        self.upsert_calls.append(self.upserted)
        self._count += len(ids)

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

    def get(self, include):
        # Same two candidates as query(), but as stored vectors for the
        # exhaustive path: query() is mocked to [0.0, 1.0, 0.0], so a 0.9
        # component gives dot=0.9 -> distance 0.10, and 0.1 -> distance 0.90 -
        # matching query()'s hardcoded distances above.
        return {
            "ids": ["7:0", "7:1"],
            "embeddings": [[0.0, 0.9, 0.0], [0.0, 0.1, 0.0]],
            "documents": ["close chunk", "far chunk"],
            "metadatas": [
                {"rag_document_id": 7, "title": "Doc", "chunk_index": 0},
                {"rag_document_id": 7, "title": "Doc", "chunk_index": 1},
            ],
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


def test_index_document_batches_upserts_under_the_server_limit(fake_collection, monkeypatch):
    # Chroma rejects a single upsert over its own batch-size ceiling outright
    # (measured live: 5,722 chunks against a server reporting 5,461) - a
    # document with more chunks than the batch size must be sliced into
    # multiple upserts, never sent in one request.
    monkeypatch.setattr(rag_service, "_MAX_UPSERT_BATCH", 2)
    chunks = ["a", "b", "c", "d", "e"]
    n = rag_service.index_document(
        "acme__rag", 7, chunks,
        workspace_slug="acme", title="Doc", kind="text", source_ref=None,
    )
    assert n == 5
    assert [len(call["ids"]) for call in fake_collection.upsert_calls] == [2, 2, 1]
    assert [i for call in fake_collection.upsert_calls for i in call["ids"]] == [
        "7:0", "7:1", "7:2", "7:3", "7:4",
    ]


def test_index_empty_chunks_stores_nothing(fake_collection):
    assert rag_service.index_document(
        "acme__rag", 7, [], workspace_slug="acme", title="Doc", kind="text", source_ref=None,
    ) == 0
    assert fake_collection.upserted is None


def test_retrieve_filters_by_max_distance(fake_collection):
    # count <= RAG_EXHAUSTIVE_MAX_CHUNKS by default, so this exercises the
    # exhaustive path (collection.get + brute-force distance).
    fake_collection._count = 2  # non-empty so retrieve issues a search
    chunks = rag_service.retrieve("acme__rag", "query", top_k=4, max_distance=0.35)
    # Only the 0.10 candidate clears the 0.35 ceiling; the 0.90 one is dropped.
    assert len(chunks) == 1
    assert chunks[0].text == "close chunk"
    assert chunks[0].distance == pytest.approx(0.10)
    assert chunks[0].rag_document_id == 7


def test_retrieve_above_exhaustive_threshold_uses_ann(fake_collection, monkeypatch):
    # Same fixture, same expected result, but forced over the threshold so
    # retrieve() must take the collection.query() (ANN) path instead.
    monkeypatch.setattr(rag_service, "RAG_EXHAUSTIVE_MAX_CHUNKS", 0)
    fake_collection._count = 2
    chunks = rag_service.retrieve("acme__rag", "query", top_k=4, max_distance=0.35)
    assert len(chunks) == 1
    assert chunks[0].text == "close chunk"
    assert chunks[0].distance == pytest.approx(0.10)


def test_exhaustive_query_ranks_by_true_distance():
    class _Col:
        def get(self, include):
            return {
                "ids": ["a", "b", "c"],
                "embeddings": [[0.0, 0.5, 0.0], [0.0, 0.9, 0.0], [0.0, 0.1, 0.0]],
                "documents": ["mid", "close", "far"],
                "metadatas": [{}, {}, {}],
            }

    docs, metas, dists = rag_service._exhaustive_query(_Col(), [0.0, 1.0, 0.0], n=2)
    # Sorted by TRUE distance ascending, not insertion order: "close" (0.9
    # dot -> 0.10 distance) first, "mid" second, "far" excluded by n=2.
    assert docs == ["close", "mid"]
    assert dists[0] == pytest.approx(0.10)
    assert dists[1] == pytest.approx(0.50)


def test_retrieve_empty_collection_returns_nothing(monkeypatch):
    class _Empty(_FakeCollection):
        def count(self):
            return 0

    monkeypatch.setattr(rag_service, "get_rag_collection", lambda ns: _Empty())
    monkeypatch.setattr(rag_service, "embed_text", lambda text: [0.0])
    assert rag_service.retrieve("acme__rag", "q", top_k=4, max_distance=0.35) == []


# --- retrieve_multi (query several texts, merge by best distance) -------------

def test_retrieve_multi_merges_and_dedupes_by_best_distance(monkeypatch):
    per_query = {
        "enriched": [
            rag_service.RagChunk(text="a", title="A", distance=0.30, rag_document_id=1, chunk_index=0),
        ],
        "original": [
            rag_service.RagChunk(text="a", title="A", distance=0.05, rag_document_id=1, chunk_index=0),
            rag_service.RagChunk(text="b", title="B", distance=0.20, rag_document_id=2, chunk_index=0),
        ],
    }
    monkeypatch.setattr(rag_service, "retrieve", lambda ns, q, top_k, max_distance: per_query[q])

    out = rag_service.retrieve_multi("acme__rag", ["enriched", "original"], top_k=4, max_distance=0.35)

    # doc 1's chunk appears under both queries; the better (lower) distance wins,
    # and doc 2 (found only via "original") is still included, sorted first-by-distance.
    assert [(c.rag_document_id, round(c.distance, 2)) for c in out] == [(1, 0.05), (2, 0.20)]


def test_retrieve_multi_dedupes_identical_query_text(monkeypatch):
    calls = []

    def fake_retrieve(ns, q, top_k, max_distance):
        calls.append(q)
        return []

    monkeypatch.setattr(rag_service, "retrieve", fake_retrieve)
    rag_service.retrieve_multi("acme__rag", ["same", "same"], top_k=4, max_distance=0.35)
    assert calls == ["same"]  # single-turn requests (enriched == original) cost one search


def test_retrieve_multi_caps_at_top_k(monkeypatch):
    chunks = [
        rag_service.RagChunk(text=str(i), title="T", distance=i / 10, rag_document_id=i, chunk_index=0)
        for i in range(5)
    ]
    monkeypatch.setattr(rag_service, "retrieve", lambda ns, q, top_k, max_distance: chunks)
    out = rag_service.retrieve_multi("acme__rag", ["q"], top_k=2, max_distance=0.35)
    assert len(out) == 2
    assert [c.rag_document_id for c in out] == [0, 1]


def test_retrieve_multi_empty_queries_returns_nothing():
    assert rag_service.retrieve_multi("acme__rag", ["", None], top_k=4, max_distance=0.35) == []


def test_delete_document_chunks_targets_the_document(fake_collection):
    rag_service.delete_document_chunks("acme__rag", 7)
    assert fake_collection.deleted_where == {"rag_document_id": 7}


def test_delete_chunk_tail_spares_the_chunks_that_were_just_reindexed(fake_collection):
    # A re-index upserts 0..keep_count-1 over the old ids, so only the leftover
    # tail of a longer previous version may be removed.
    rag_service.delete_chunk_tail("acme__rag", 7, 3)
    assert fake_collection.deleted_where == {
        "$and": [
            {"rag_document_id": {"$eq": 7}},
            {"chunk_index": {"$gte": 3}},
        ]
    }


# --- retrieve_by_document: the explicit `@`-reference path --------------------

class _FakeFilteredCollection:
    """Mirrors _FakeCollection, but records the `where` filter and returns
    chunks from only ONE document — standing in for a real Chroma metadata
    filter, which `_FakeCollection.query` above doesn't accept at all."""

    def __init__(self):
        self.last_where = None
        self._count = 5136  # a large mixed collection — the crowd-out population

    def count(self):
        return self._count

    def query(self, query_embeddings, n_results, where, include):
        self.last_where = where
        target = where["rag_document_id"]
        # A repository reference filters on a SET of ids ($in); a single-file
        # reference on one. Both come back through the same shape.
        doc_id = target["$in"][0] if isinstance(target, dict) else target
        # A document far outside the automatic search's max_distance would
        # still come back here — there is no distance gate on this path.
        return {
            "ids": [[f"{doc_id}:0", f"{doc_id}:1"]],
            "documents": [["own chunk one", "own chunk two"]],
            "metadatas": [[
                {"rag_document_id": doc_id, "title": "Referenced Doc", "chunk_index": 0},
                {"rag_document_id": doc_id, "title": "Referenced Doc", "chunk_index": 1},
            ]],
            "distances": [[0.62, 0.71]],  # both well past DEJAQ_RAG_MAX_DISTANCE
        }


@pytest.fixture
def fake_filtered_collection(monkeypatch):
    col = _FakeFilteredCollection()
    monkeypatch.setattr(rag_service, "get_rag_collection", lambda ns: col)
    monkeypatch.setattr(rag_service, "embed_text", lambda text: [0.0, 1.0, 0.0])
    return col


def test_retrieve_by_document_filters_on_the_document_id(fake_filtered_collection):
    chunks = rag_service.retrieve_by_document("acme__rag", 7, "some question", top_k=4)
    assert fake_filtered_collection.last_where == {"rag_document_id": 7}
    assert [c.rag_document_id for c in chunks] == [7, 7]


def test_retrieve_by_document_has_no_distance_gate(fake_filtered_collection):
    # Unlike retrieve(), a chunk is returned regardless of distance: the
    # document is already pinned by id, not by how close the embedding is.
    chunks = rag_service.retrieve_by_document("acme__rag", 7, "some question", top_k=4)
    assert len(chunks) == 2
    assert chunks[0].distance == pytest.approx(0.62)


def test_retrieve_by_document_empty_collection_returns_nothing(monkeypatch):
    class _Empty(_FakeFilteredCollection):
        def count(self):
            return 0

    monkeypatch.setattr(rag_service, "get_rag_collection", lambda ns: _Empty())
    monkeypatch.setattr(rag_service, "embed_text", lambda text: [0.0])
    assert rag_service.retrieve_by_document("acme__rag", 7, "q", top_k=4) == []


# --- retrieve_by_documents: the whole-repository reference path ---------------
#
# One imported repository is one catalog row PER FILE, so a reference to the
# repository pins a SET of ids. Same filter, same absent distance gate - just
# `$in` instead of equality.


def test_retrieve_by_documents_filters_on_every_id_in_the_group(fake_filtered_collection):
    chunks = rag_service.retrieve_by_documents("acme__rag", [11, 13, 12], "q", top_k=4)
    assert fake_filtered_collection.last_where == {"rag_document_id": {"$in": [11, 12, 13]}}
    assert len(chunks) == 2


def test_retrieve_by_documents_uses_plain_equality_for_a_single_id(fake_filtered_collection):
    # A one-element `$in` is the same query as equality, and Chroma is happier
    # with the simple form - so a single-file reference is unchanged by this.
    rag_service.retrieve_by_documents("acme__rag", [7, 7], "q", top_k=4)
    assert fake_filtered_collection.last_where == {"rag_document_id": 7}


def test_retrieve_by_documents_with_no_ids_returns_nothing(fake_filtered_collection):
    # An emptied group (every file deleted) must not fall back to searching the
    # whole collection - that is exactly the crowd-out this path avoids.
    assert rag_service.retrieve_by_documents("acme__rag", [], "q", top_k=4) == []
    assert fake_filtered_collection.last_where is None
