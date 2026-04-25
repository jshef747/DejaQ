import sqlite3

from fastapi.testclient import TestClient


def _client(admin_token_env):
    from app.main import app

    admin_token_env("admin-secret")
    return TestClient(app), {"Authorization": "Bearer admin-secret"}


def test_admin_departments_round_trip(isolated_org_db, admin_token_env):
    client, headers = _client(admin_token_env)
    client.post("/admin/v1/orgs", json={"name": "Acme"}, headers=headers)

    created = client.post(
        "/admin/v1/orgs/acme/departments",
        json={"name": "Engineering"},
        headers=headers,
    )
    scoped = client.get("/admin/v1/departments?org=acme", headers=headers)
    unscoped = client.get("/admin/v1/departments", headers=headers)
    deleted = client.delete("/admin/v1/orgs/acme/departments/engineering", headers=headers)

    assert created.status_code == 201
    assert created.json()["org_slug"] == "acme"
    assert scoped.status_code == 200
    assert [item["slug"] for item in scoped.json()] == ["engineering"]
    assert unscoped.json()[0]["org_slug"] == "acme"
    assert deleted.json() == {"deleted": True, "cache_namespace": "acme__engineering"}


def test_admin_keys_mask_rotate_and_revoke(isolated_org_db, admin_token_env):
    client, headers = _client(admin_token_env)
    client.post("/admin/v1/orgs", json={"name": "Acme"}, headers=headers)

    first = client.post("/admin/v1/orgs/acme/keys", headers=headers)
    conflict = client.post("/admin/v1/orgs/acme/keys", headers=headers)
    second = client.post("/admin/v1/orgs/acme/keys?force=true", headers=headers)
    listed = client.get("/admin/v1/orgs/acme/keys", headers=headers)
    revoked = client.delete(f"/admin/v1/keys/{second.json()['id']}", headers=headers)
    revoked_again = client.delete(f"/admin/v1/keys/{second.json()['id']}", headers=headers)

    assert first.status_code == 201
    assert "token" in first.json()
    assert conflict.status_code == 409
    assert second.status_code == 201
    assert listed.status_code == 200
    assert all("token" not in item for item in listed.json())
    assert all(item["token_prefix"].endswith("...") for item in listed.json())
    assert revoked.json()["already_revoked"] is False
    assert revoked_again.json()["already_revoked"] is True


def test_admin_stats_date_filters_and_unknown_org(isolated_org_db, isolated_stats_db, admin_token_env):
    client, headers = _client(admin_token_env)
    client.post("/admin/v1/orgs", json={"name": "Acme"}, headers=headers)
    con = sqlite3.connect(isolated_stats_db)
    con.execute(
        """CREATE TABLE requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, org TEXT NOT NULL, department TEXT NOT NULL,
            latency_ms INTEGER NOT NULL, cache_hit INTEGER NOT NULL,
            difficulty TEXT, model_used TEXT, response_id TEXT
        )"""
    )
    con.executemany(
        "INSERT INTO requests (ts, org, department, latency_ms, cache_hit, difficulty, model_used, response_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("2026-04-01T00:00:00+00:00", "acme", "eng", 100, 1, "easy", "cache", "r1"),
            ("2026-04-15T00:00:00+00:00", "acme", "eng", 200, 0, "hard", "gemini", "r2"),
        ],
    )
    con.commit()
    con.close()

    orgs = client.get("/admin/v1/stats/orgs?from=2026-04-01&to=2026-04-15", headers=headers)
    reversed_range = client.get("/admin/v1/stats/orgs?from=2026-04-15&to=2026-04-01", headers=headers)
    unknown = client.get("/admin/v1/stats/orgs/missing/departments", headers=headers)

    assert orgs.status_code == 200
    assert orgs.json()["total"]["requests"] == 1
    assert reversed_range.status_code == 422
    assert unknown.status_code == 404


def test_admin_llm_config_defaults_update_and_clear(isolated_org_db, admin_token_env):
    client, headers = _client(admin_token_env)
    client.post("/admin/v1/orgs", json={"name": "Acme"}, headers=headers)

    defaulted = client.get("/admin/v1/orgs/acme/llm-config", headers=headers)
    updated = client.put(
        "/admin/v1/orgs/acme/llm-config",
        json={"external_model": "gemini-2.5-pro"},
        headers=headers,
    )
    cleared = client.put(
        "/admin/v1/orgs/acme/llm-config",
        json={"external_model": None},
        headers=headers,
    )
    empty = client.put("/admin/v1/orgs/acme/llm-config", json={}, headers=headers)

    assert defaulted.status_code == 200
    assert defaulted.json()["is_default"] is True
    assert updated.json()["overrides"] == {"external_model": "gemini-2.5-pro"}
    assert cleared.json()["overrides"] == {}
    assert empty.status_code == 422


def test_admin_feedback_submit_and_list(isolated_org_db, isolated_stats_db, admin_token_env, monkeypatch):
    from app.services import feedback_service
    from tests.test_feedback_service import FakeMemory

    client, headers = _client(admin_token_env)
    client.post("/admin/v1/orgs", json={"name": "Acme"}, headers=headers)
    client.post("/admin/v1/orgs/acme/departments", json={"name": "Eng"}, headers=headers)

    memory = FakeMemory()
    monkeypatch.setattr(feedback_service, "get_memory_service", lambda namespace: memory)

    async def _log_feedback(response_id, org, department, rating, comment):
        con = sqlite3.connect(isolated_stats_db)
        con.execute(
            """CREATE TABLE IF NOT EXISTS feedback_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                response_id TEXT NOT NULL,
                org TEXT NOT NULL,
                department TEXT NOT NULL,
                rating TEXT NOT NULL,
                comment TEXT
            )"""
        )
        con.execute(
            "INSERT INTO feedback_log (ts, response_id, org, department, rating, comment) VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-04-01T00:00:00+00:00", response_id, org, department, rating, comment),
        )
        con.commit()
        con.close()

    monkeypatch.setattr(feedback_service.request_logger, "log_feedback", _log_feedback)

    submit = client.post(
        "/admin/v1/feedback",
        json={"org": "acme", "department": "eng", "response_id": "acme__eng:doc1", "rating": "positive"},
        headers=headers,
    )
    mismatch = client.post(
        "/admin/v1/feedback",
        json={"org": "acme", "department": "eng", "response_id": "other__eng:doc1", "rating": "positive"},
        headers=headers,
    )
    filtered = client.get("/admin/v1/feedback?org=acme&department=eng", headers=headers)
    unknown_filter = client.get("/admin/v1/feedback?org=missing", headers=headers)

    assert submit.status_code == 200
    assert submit.json() == {"status": "ok", "new_score": 1.0}
    assert mismatch.status_code == 422
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert unknown_filter.json()["items"] == []


def test_admin_feedback_list_id_field_and_pagination_total(
    isolated_org_db, isolated_stats_db, admin_token_env
):
    """id field is present in items; total reflects pre-pagination count."""
    import sqlite3 as _sqlite3

    client, headers = _client(admin_token_env)

    # Seed feedback_log directly with 3 rows.
    con = _sqlite3.connect(isolated_stats_db)
    con.execute(
        """CREATE TABLE IF NOT EXISTS feedback_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            response_id TEXT NOT NULL,
            org TEXT NOT NULL,
            department TEXT NOT NULL,
            rating TEXT NOT NULL,
            comment TEXT
        )"""
    )
    con.executemany(
        "INSERT INTO feedback_log (ts, response_id, org, department, rating, comment) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("2026-04-01T00:00:00+00:00", "ns:doc-a", "acme", "eng", "positive", None),
            ("2026-04-02T00:00:00+00:00", "ns:doc-b", "acme", "eng", "negative", None),
            ("2026-04-03T00:00:00+00:00", "ns:doc-c", "acme", "eng", "positive", None),
        ],
    )
    con.commit()
    con.close()

    # limit=1 — total must still be 3 (pre-pagination count).
    page1 = client.get("/admin/v1/feedback?org=acme&limit=1&offset=0", headers=headers)

    assert page1.status_code == 200
    body = page1.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    # Every item must carry an 'id' field.
    assert "id" in body["items"][0]


def test_admin_feedback_list_ordering_ts_desc_id_desc(
    isolated_org_db, isolated_stats_db, admin_token_env
):
    """Results are ordered by ts DESC then id DESC."""
    import sqlite3 as _sqlite3

    client, headers = _client(admin_token_env)

    con = _sqlite3.connect(isolated_stats_db)
    con.execute(
        """CREATE TABLE IF NOT EXISTS feedback_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            response_id TEXT NOT NULL,
            org TEXT NOT NULL,
            department TEXT NOT NULL,
            rating TEXT NOT NULL,
            comment TEXT
        )"""
    )
    # Two rows share the same ts — ordering must fall back to id DESC.
    con.executemany(
        "INSERT INTO feedback_log (ts, response_id, org, department, rating, comment) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("2026-04-01T00:00:00+00:00", "ns:older", "acme", "eng", "positive", None),
            ("2026-04-03T00:00:00+00:00", "ns:newest", "acme", "eng", "positive", None),
            ("2026-04-03T00:00:00+00:00", "ns:tie-lower-id", "acme", "eng", "negative", None),
        ],
    )
    con.commit()
    con.close()

    resp = client.get("/admin/v1/feedback?org=acme", headers=headers)

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    # The two ts=2026-04-03 rows must come first; the one inserted last (higher id) appears first.
    assert items[0]["response_id"] == "ns:tie-lower-id"
    assert items[1]["response_id"] == "ns:newest"
    assert items[2]["response_id"] == "ns:older"


def test_stats_org_name_and_department_name_return_display_name(
    isolated_org_db, isolated_stats_db, admin_token_env
):
    """org_name / department_name must return the human display name, not the slug."""
    client, headers = _client(admin_token_env)
    client.post("/admin/v1/orgs", json={"name": "Acme Corporation"}, headers=headers)
    client.post("/admin/v1/orgs/acme-corporation/departments", json={"name": "Engineering"}, headers=headers)

    con = sqlite3.connect(isolated_stats_db)
    con.execute(
        """CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, org TEXT NOT NULL, department TEXT NOT NULL,
            latency_ms INTEGER NOT NULL, cache_hit INTEGER NOT NULL,
            difficulty TEXT, model_used TEXT, response_id TEXT
        )"""
    )
    con.execute(
        "INSERT INTO requests (ts, org, department, latency_ms, cache_hit, difficulty, model_used, response_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-04-01T00:00:00+00:00", "acme-corporation", "engineering", 100, 1, "easy", "cache", "r1"),
    )
    con.commit()
    con.close()

    orgs = client.get("/admin/v1/stats/orgs", headers=headers)
    depts = client.get("/admin/v1/stats/orgs/acme-corporation/departments", headers=headers)

    assert orgs.status_code == 200
    assert orgs.json()["items"][0]["org_name"] == "Acme Corporation"

    assert depts.status_code == 200
    assert depts.json()["items"][0]["department_name"] == "Engineering"


def test_departments_list_unknown_org_filter_returns_empty_list(isolated_org_db, admin_token_env):
    """GET /departments?org=missing returns 200 empty list, consistent with other list filters."""
    client, headers = _client(admin_token_env)

    resp = client.get("/admin/v1/departments?org=does-not-exist", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == []


def test_stats_invalid_date_format_returns_422(isolated_org_db, isolated_stats_db, admin_token_env):
    """Invalid date format in ?from or ?to must return 422."""
    client, headers = _client(admin_token_env)

    resp = client.get("/admin/v1/stats/orgs?from=04/01/2026", headers=headers)

    assert resp.status_code == 422


def test_llm_config_unknown_org_returns_404(isolated_org_db, admin_token_env):
    """GET /admin/v1/orgs/{slug}/llm-config for unknown org must return 404."""
    client, headers = _client(admin_token_env)

    resp = client.get("/admin/v1/orgs/does-not-exist/llm-config", headers=headers)

    assert resp.status_code == 404
