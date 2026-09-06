"""Tests for the dashboard Cache browser admin API.

Uses a scratch ChromaDB instance (see the module-level `_chroma_available`
check) seeded directly with fixed embeddings, mirroring
`tests/test_memory_chromadb.py`'s `chroma_required` pattern — no model loads,
no provider calls.
"""

import chromadb
import pytest

from app.services import admin_service, cache_admin_service, memory_chromaDB

SCRATCH_CHROMA_HOST = "127.0.0.1"
SCRATCH_CHROMA_PORT = 19102


def _chroma_available() -> bool:
    try:
        chromadb.HttpClient(host=SCRATCH_CHROMA_HOST, port=SCRATCH_CHROMA_PORT).heartbeat()
        return True
    except Exception:
        return False


chroma_required = pytest.mark.skipif(
    not _chroma_available(), reason="scratch ChromaDB server not available on 19102"
)

pytestmark = [pytest.mark.no_model, chroma_required]


def _wipe_scratch_collections() -> None:
    client = chromadb.HttpClient(host=SCRATCH_CHROMA_HOST, port=SCRATCH_CHROMA_PORT)
    for collection in client.list_collections():
        name = collection if isinstance(collection, str) else collection.name
        client.delete_collection(name)


@pytest.fixture(autouse=True)
def _use_scratch_chroma(monkeypatch):
    monkeypatch.setattr(cache_admin_service, "CHROMA_HOST", SCRATCH_CHROMA_HOST)
    monkeypatch.setattr(cache_admin_service, "CHROMA_PORT", SCRATCH_CHROMA_PORT)
    monkeypatch.setattr(memory_chromaDB, "CHROMA_HOST", SCRATCH_CHROMA_HOST)
    monkeypatch.setattr(memory_chromaDB, "CHROMA_PORT", SCRATCH_CHROMA_PORT)
    memory_chromaDB._pool.clear()
    _wipe_scratch_collections()
    yield
    memory_chromaDB._pool.clear()
    _wipe_scratch_collections()


def _scratch_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(host=SCRATCH_CHROMA_HOST, port=SCRATCH_CHROMA_PORT)


def _seed(
    namespace: str,
    doc_id: str,
    *,
    normalized_query: str,
    answer: str,
    original_query: str | None = None,
    alias_of: str | None = None,
    authored: str | None = None,
    score: float = 0.0,
    hit_count: int = 0,
    negative_count: int = 0,
    user_id: str = "seed-user",
    stored_at: str = "2026-01-01T00:00:00Z",
    embedding: list[float] | None = None,
) -> None:
    client = _scratch_client()
    collection = client.get_or_create_collection(name=namespace, metadata={"hnsw:space": "cosine"})
    meta: dict = {
        "generalized_answer": answer,
        "original_query": original_query if original_query is not None else normalized_query,
        "user_id": user_id,
        "stored_at": stored_at,
        "score": score,
        "hit_count": hit_count,
        "negative_count": negative_count,
    }
    if alias_of:
        meta["alias_of"] = alias_of
    if authored:
        meta["authored"] = authored
    collection.upsert(
        ids=[doc_id],
        embeddings=[embedding or [1.0, 0.0, 0.0, 0.0]],
        documents=[normalized_query],
        metadatas=[meta],
    )


def _make_workspace(client, headers, name: str) -> str:
    resp = client.post("/admin/v1/workspaces", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["slug"]


def _make_department(client, headers, workspace_slug: str, name: str) -> dict:
    resp = client.post(
        f"/admin/v1/workspaces/{workspace_slug}/departments", json={"name": name}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── workspace / department resolution ──


def test_unknown_workspace_returns_404(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    resp = client.get(
        "/admin/v1/workspaces/no-such-workspace/cache-entries",
        params={"department": "support"},
        headers=headers,
    )
    assert resp.status_code == 404


def test_unknown_department_returns_404(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    resp = client.get(
        f"/admin/v1/workspaces/{slug}/cache-entries",
        params={"department": "no-such-dept"},
        headers=headers,
    )
    assert resp.status_code == 404


# ── missing collection ──


def test_missing_collection_returns_empty_page_without_creating_it(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")
    namespace = dept["cache_namespace"]

    scratch = _scratch_client()
    existing_before = {c.name for c in scratch.list_collections()}
    assert namespace not in existing_before

    resp = client.get(
        f"/admin/v1/workspaces/{slug}/cache-entries",
        params={"department": dept["slug"]},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["cache_namespace"] == namespace

    existing_after = {c.name for c in scratch.list_collections()}
    assert namespace not in existing_after


# ── namespace isolation ──


def test_workspace_and_department_namespace_isolation(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    ws_a = _make_workspace(client, headers, "PlanWS")
    dept_support = _make_department(client, headers, ws_a, "Support")
    dept_sales = _make_department(client, headers, ws_a, "Sales")
    ws_b = _make_workspace(client, headers, "OtherWS")
    dept_other = _make_department(client, headers, ws_b, "Support")

    _seed(dept_support["cache_namespace"], "s1", normalized_query="support q1", answer="a1")
    _seed(dept_sales["cache_namespace"], "sale1", normalized_query="sales q1", answer="b1")
    _seed(dept_other["cache_namespace"], "o1", normalized_query="other q1", answer="c1")

    resp = client.get(
        f"/admin/v1/workspaces/{ws_a}/cache-entries",
        params={"department": dept_support["slug"]},
        headers=headers,
    )
    body = resp.json()
    assert body["total"] == 1
    ids = [item["id"] for item in body["items"]]
    assert ids == ["s1"]
    assert "sale1" not in ids
    assert "o1" not in ids


# ── pagination boundaries ──


def test_pagination_boundaries(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")
    namespace = dept["cache_namespace"]

    for i in range(5):
        _seed(namespace, f"e{i}", normalized_query=f"query {i}", answer=f"answer {i}")

    page1 = client.get(
        f"/admin/v1/workspaces/{slug}/cache-entries",
        params={"department": dept["slug"], "limit": 2, "offset": 0},
        headers=headers,
    ).json()
    assert page1["total"] == 5
    assert len(page1["items"]) == 2

    page3 = client.get(
        f"/admin/v1/workspaces/{slug}/cache-entries",
        params={"department": dept["slug"], "limit": 2, "offset": 4},
        headers=headers,
    ).json()
    assert len(page3["items"]) == 1

    over_limit = client.get(
        f"/admin/v1/workspaces/{slug}/cache-entries",
        params={"department": dept["slug"], "limit": 1000},
        headers=headers,
    )
    assert over_limit.status_code == 422

    negative_offset = client.get(
        f"/admin/v1/workspaces/{slug}/cache-entries",
        params={"department": dept["slug"], "offset": -1},
        headers=headers,
    )
    assert negative_offset.status_code == 422

    default_page = client.get(
        f"/admin/v1/workspaces/{slug}/cache-entries",
        params={"department": dept["slug"]},
        headers=headers,
    ).json()
    assert default_page["limit"] == 50
    assert len(default_page["items"]) == 5


# ── sensitive fields / text capping ──


def test_sensitive_fields_absent_and_text_capped(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")
    namespace = dept["cache_namespace"]

    long_answer = "x" * 5000
    long_query = "y" * 1000
    _seed(
        namespace,
        "e1",
        normalized_query=long_query,
        answer=long_answer,
        original_query=long_query,
        user_id="a-real-user-id",
    )

    resp = client.get(
        f"/admin/v1/workspaces/{slug}/cache-entries",
        params={"department": dept["slug"]},
        headers=headers,
    )
    body = resp.json()
    raw_text = resp.text
    assert "a-real-user-id" not in raw_text
    assert '"user_id"' not in raw_text
    assert '"embedding' not in raw_text
    assert '"image_clip"' not in raw_text
    assert '"image_dhash"' not in raw_text
    assert '"file_sha"' not in raw_text

    item = body["items"][0]
    assert len(item["answer_preview"]) <= cache_admin_service.ANSWER_PREVIEW_CHARS
    assert len(item["original_query_preview"]) <= cache_admin_service.QUERY_PREVIEW_CHARS
    assert len(item["normalized_query_preview"]) <= cache_admin_service.QUERY_PREVIEW_CHARS
    assert item["text_truncated"] is True


# ── answer edit ──


def test_edit_preserves_normalized_query_and_embedding(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")
    namespace = dept["cache_namespace"]
    embedding = [0.2, 0.4, 0.6, 0.8]
    _seed(namespace, "root1", normalized_query="how do i reset sso", answer="old answer", embedding=embedding)

    scratch = _scratch_client()
    collection = scratch.get_collection(namespace)
    before = collection.get(ids=["root1"], include=["embeddings", "documents"])

    resp = client.put(
        f"/admin/v1/workspaces/{slug}/cache-entries/root1",
        params={"department": dept["slug"]},
        json={"answer": "new answer"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": "root1", "redirected": False}

    after = collection.get(ids=["root1"], include=["embeddings", "documents", "metadatas"])
    assert list(after["embeddings"][0]) == list(before["embeddings"][0])
    assert after["documents"][0] == before["documents"][0] == "how do i reset sso"
    assert after["metadatas"][0]["generalized_answer"] == "new answer"
    assert after["metadatas"][0]["authored"] == "human"


def test_edit_redirects_alias_to_root_and_updates_all_aliases(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")
    namespace = dept["cache_namespace"]

    _seed(namespace, "root1", normalized_query="how do i reset sso", answer="old answer")
    _seed(namespace, "alias1", normalized_query="how do i rset sso", answer="old answer", alias_of="root1")
    _seed(namespace, "alias2", normalized_query="how do i reset sso ", answer="old answer", alias_of="root1")

    resp = client.put(
        f"/admin/v1/workspaces/{slug}/cache-entries/alias1",
        params={"department": dept["slug"]},
        json={"answer": "corrected answer"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": "root1", "redirected": True}

    scratch = _scratch_client()
    collection = scratch.get_collection(namespace)
    result = collection.get(ids=["root1", "alias1", "alias2"], include=["metadatas"])
    answers = {doc_id: meta["generalized_answer"] for doc_id, meta in zip(result["ids"], result["metadatas"])}
    assert answers == {
        "root1": "corrected answer",
        "alias1": "corrected answer",
        "alias2": "corrected answer",
    }


@pytest.mark.parametrize(
    "answer,expected_status",
    [
        ("", 422),
        ("   ", 422),
        ("x" * 300_000, 422),
    ],
)
def test_edit_invalid_answers_return_clear_errors(isolated_org_db, authed_admin_client, answer, expected_status):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")
    namespace = dept["cache_namespace"]
    _seed(namespace, "root1", normalized_query="q", answer="a")

    resp = client.put(
        f"/admin/v1/workspaces/{slug}/cache-entries/root1",
        params={"department": dept["slug"]},
        json={"answer": answer},
        headers=headers,
    )
    assert resp.status_code == expected_status


def test_edit_missing_entry_returns_404(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")

    resp = client.put(
        f"/admin/v1/workspaces/{slug}/cache-entries/does-not-exist",
        params={"department": dept["slug"]},
        json={"answer": "new answer"},
        headers=headers,
    )
    assert resp.status_code == 404


def test_edit_missing_body_field_returns_422(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")

    resp = client.put(
        f"/admin/v1/workspaces/{slug}/cache-entries/root1",
        params={"department": dept["slug"]},
        json={},
        headers=headers,
    )
    assert resp.status_code == 422


# ── deletion ──


def test_delete_removes_root_and_its_aliases(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")
    namespace = dept["cache_namespace"]

    _seed(namespace, "root1", normalized_query="how do i reset sso", answer="a")
    _seed(namespace, "alias1", normalized_query="how do i rset sso", answer="a", alias_of="root1")

    resp = client.delete(
        f"/admin/v1/workspaces/{slug}/cache-entries/root1",
        params={"department": dept["slug"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"id": "root1", "deleted": True}

    scratch = _scratch_client()
    collection = scratch.get_collection(namespace)
    remaining = collection.get(ids=["root1", "alias1"])
    assert remaining["ids"] == []


def test_delete_missing_entry_returns_404(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")
    dept = _make_department(client, headers, slug, "Support")
    namespace = dept["cache_namespace"]
    _seed(namespace, "root1", normalized_query="q", answer="a")

    resp = client.delete(
        f"/admin/v1/workspaces/{slug}/cache-entries/does-not-exist",
        params={"department": dept["slug"]},
        headers=headers,
    )
    assert resp.status_code == 404


def test_delete_unknown_department_returns_404(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client
    slug = _make_workspace(client, headers, "Acme")

    resp = client.delete(
        f"/admin/v1/workspaces/{slug}/cache-entries/anything",
        params={"department": "no-such-dept"},
        headers=headers,
    )
    assert resp.status_code == 404
