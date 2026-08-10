"""
User-actor org scoping tests.

Every admin route that operates on a specific org must:
- Return 403 when a user actor lacks membership in that org
- Return 200/201 when the user actor has membership in that org

These tests use the `scoped_admin_client` fixture, which injects a user actor
with a controlled list of accessible orgs, bypassing real Supabase validation.
"""
import pytest


def _make_workspace_ref(workspace_id: int, name: str, slug: str):
    from app.dependencies.management_auth import WorkspaceRef
    from datetime import datetime, timezone

    return WorkspaceRef(id=workspace_id, name=name, slug=slug, created_at=datetime.now(timezone.utc))


@pytest.fixture
def seeded_db(isolated_org_db, authed_admin_client):
    """Create acme workspace + eng department via system actor; return their IDs."""
    client, headers = authed_admin_client
    ws_resp = client.post("/admin/v1/workspaces", json={"name": "Acme"}, headers=headers)
    assert ws_resp.status_code == 201
    workspace_id = ws_resp.json()["id"]

    dept_resp = client.post(
        "/admin/v1/workspaces/acme/departments", json={"name": "Eng"}, headers=headers
    )
    assert dept_resp.status_code == 201

    key_resp = client.post("/admin/v1/workspaces/acme/keys", headers=headers)
    assert key_resp.status_code == 201
    key_id = key_resp.json()["id"]

    return {"workspace_id": workspace_id, "workspace_slug": "acme", "key_id": key_id}


# ── org routes ────────────────────────────────────────────────────────────────

def test_user_actor_delete_org_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])  # no memberships
    resp = client.delete("/admin/v1/workspaces/acme", headers=headers)
    assert resp.status_code == 403


def test_user_actor_delete_org_allowed_with_membership(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.delete("/admin/v1/workspaces/acme", headers=headers)
    assert resp.status_code == 200


def test_user_actor_list_orgs_scoped_to_memberships(seeded_db, scoped_admin_client):
    """User actor only sees orgs they're a member of."""
    client, headers = scoped_admin_client([])  # no memberships
    resp = client.get("/admin/v1/workspaces", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_user_actor_list_orgs_sees_accessible_org(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.get("/admin/v1/workspaces", headers=headers)
    assert resp.status_code == 200
    slugs = [o["slug"] for o in resp.json()]
    assert "acme" in slugs


# ── department routes ─────────────────────────────────────────────────────────

def test_user_actor_create_department_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.post(
        "/admin/v1/workspaces/acme/departments", json={"name": "Sales"}, headers=headers
    )
    assert resp.status_code == 403


def test_user_actor_create_department_allowed_with_membership(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.post(
        "/admin/v1/workspaces/acme/departments", json={"name": "Sales"}, headers=headers
    )
    assert resp.status_code == 201


def test_user_actor_delete_department_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.delete("/admin/v1/workspaces/acme/departments/eng", headers=headers)
    assert resp.status_code == 403


def test_user_actor_delete_department_allowed_with_membership(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.delete("/admin/v1/workspaces/acme/departments/eng", headers=headers)
    assert resp.status_code == 200


# ── key routes ────────────────────────────────────────────────────────────────

def test_user_actor_list_keys_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.get("/admin/v1/workspaces/acme/keys", headers=headers)
    assert resp.status_code == 403


def test_user_actor_list_keys_allowed_with_membership(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.get("/admin/v1/workspaces/acme/keys", headers=headers)
    assert resp.status_code == 200


def test_user_actor_generate_key_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.post("/admin/v1/workspaces/acme/keys?force=true", headers=headers)
    assert resp.status_code == 403


def test_user_actor_revoke_key_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.delete(f"/admin/v1/keys/{seeded_db['key_id']}", headers=headers)
    assert resp.status_code == 403


def test_user_actor_revoke_key_allowed_with_membership(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.delete(f"/admin/v1/keys/{seeded_db['key_id']}", headers=headers)
    assert resp.status_code == 200


def test_user_actor_delete_revoked_key_forbidden_without_membership(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    member_client, member_headers = scoped_admin_client([org_ref])
    member_client.delete(f"/admin/v1/keys/{seeded_db['key_id']}", headers=member_headers)

    client, headers = scoped_admin_client([])
    resp = client.delete(f"/admin/v1/keys/{seeded_db['key_id']}/revoked", headers=headers)
    assert resp.status_code == 403


def test_user_actor_delete_revoked_key_allowed_with_membership(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    client.delete(f"/admin/v1/keys/{seeded_db['key_id']}", headers=headers)

    resp = client.delete(f"/admin/v1/keys/{seeded_db['key_id']}/revoked", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"id": seeded_db["key_id"], "deleted": True}


# ── stats routes ──────────────────────────────────────────────────────────────

def test_user_actor_dept_stats_forbidden_without_membership(seeded_db, isolated_stats_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.get("/admin/v1/stats/workspaces/acme/departments", headers=headers)
    assert resp.status_code == 403


def test_user_actor_dept_stats_allowed_with_membership(seeded_db, isolated_stats_db, scoped_admin_client):
    import sqlite3

    con = sqlite3.connect(isolated_stats_db)
    con.execute(
        """CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, workspace TEXT NOT NULL, department TEXT NOT NULL,
            latency_ms INTEGER NOT NULL, cache_hit INTEGER NOT NULL,
            difficulty TEXT, model_used TEXT, response_id TEXT
        )"""
    )
    con.commit()
    con.close()

    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.get("/admin/v1/stats/workspaces/acme/departments", headers=headers)
    assert resp.status_code == 200


# ── llm-config routes ─────────────────────────────────────────────────────────

def test_user_actor_read_llm_config_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.get("/admin/v1/workspaces/acme/llm-config", headers=headers)
    assert resp.status_code == 403


def test_user_actor_read_llm_config_allowed_with_membership(seeded_db, scoped_admin_client):
    org_ref = _make_workspace_ref(seeded_db["workspace_id"], "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.get("/admin/v1/workspaces/acme/llm-config", headers=headers)
    assert resp.status_code == 200


def test_user_actor_update_llm_config_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.put(
        "/admin/v1/workspaces/acme/llm-config",
        json={"external_model": "gemini-2.5-pro"},
        headers=headers,
    )
    assert resp.status_code == 403


# ── credentials routes ───────────────────────────────────────────────────────

def test_user_actor_list_credentials_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.get("/admin/v1/workspaces/acme/credentials", headers=headers)
    assert resp.status_code == 403


def test_user_actor_upsert_credentials_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.put(
        "/admin/v1/workspaces/acme/credentials/google",
        json={"api_key": "AIzaFoo123Bar"},
        headers=headers,
    )
    assert resp.status_code == 403


def test_user_actor_delete_credentials_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.delete("/admin/v1/workspaces/acme/credentials/google", headers=headers)
    assert resp.status_code == 403


# ── provider test route ──────────────────────────────────────────────────────

def test_user_actor_test_provider_forbidden_without_membership(seeded_db, scoped_admin_client):
    client, headers = scoped_admin_client([])
    resp = client.post(
        "/admin/v1/workspaces/acme/test-provider",
        json={"model": "gemini-2.5-flash"},
        headers=headers,
    )
    assert resp.status_code == 403


# ── whoami ────────────────────────────────────────────────────────────────────

def test_user_actor_whoami_returns_user_info(isolated_org_db, scoped_admin_client):
    org_ref = _make_workspace_ref(99, "Acme", "acme")
    client, headers = scoped_admin_client([org_ref])
    resp = client.get("/admin/v1/whoami", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["actor_type"] == "user"
    assert data["email"] == "test@example.com"
    assert any(o["slug"] == "acme" for o in data["workspaces"])


# ── auto-membership on org creation ──────────────────────────────────────────

def test_user_actor_gets_membership_on_workspace_create(isolated_org_db, scoped_admin_client):
    """When a user actor creates a workspace, they should automatically be a member in the DB."""
    from app.db.session import get_session
    from app.db.models.user import ManagementUser
    from app.db.models.workspace import Workspace
    from app.db.models.user_workspace_membership import UserWorkspaceMembership

    # The scoped_admin_client injects local_user_id=1; seed the matching user row
    # so the FK constraint on user_workspace_memberships is satisfied.
    with get_session() as session:
        user = ManagementUser(id=1, supabase_user_id="test-supabase-uid", email="test@example.com")
        session.add(user)

    client, headers = scoped_admin_client([])  # no pre-existing memberships

    create_resp = client.post("/admin/v1/workspaces", json={"name": "New Org"}, headers=headers)
    assert create_resp.status_code == 201

    new_slug = create_resp.json()["slug"]

    with get_session() as session:
        workspace = session.query(Workspace).filter_by(slug=new_slug).first()
        assert workspace is not None
        membership = session.query(UserWorkspaceMembership).filter_by(
            user_id=1, workspace_id=workspace.id
        ).first()
        assert membership is not None, "Auto-membership not created for user actor on workspace create"
