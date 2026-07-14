from fastapi.testclient import TestClient


def test_admin_whoami_reachable_without_auth_in_local_mode():
    """In local auth mode (default), whoami returns 200 with the dev-admin context."""
    from app.main import app

    client = TestClient(app)
    resp = client.get("/admin/v1/whoami")
    # Local mode returns dev-admin context; no token needed.
    assert resp.status_code == 200
    assert resp.json()["authorized"] is True


def test_admin_whoami_returns_user_info(authed_admin_client):
    client, headers = authed_admin_client
    resp = client.get("/admin/v1/whoami", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["authorized"] is True
    assert data["actor_type"] == "system"


def test_admin_workspace_create_list_delete_round_trip(isolated_org_db, authed_admin_client):
    client, headers = authed_admin_client

    created = client.post("/admin/v1/workspaces", json={"name": "Acme"}, headers=headers)
    listed = client.get("/admin/v1/workspaces", headers=headers)
    deleted = client.delete("/admin/v1/workspaces/acme", headers=headers)

    assert created.status_code == 201
    assert created.json()["slug"] == "acme"
    assert listed.status_code == 200
    assert [item["slug"] for item in listed.json()] == ["acme"]
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "departments_removed": 0}
