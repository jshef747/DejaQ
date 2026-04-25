from fastapi.testclient import TestClient


def test_admin_whoami_requires_admin_token(admin_token_env):
    from app.main import app

    admin_token_env("admin-secret")
    client = TestClient(app)

    missing = client.get("/admin/v1/whoami")
    ok = client.get("/admin/v1/whoami", headers={"Authorization": "Bearer admin-secret"})

    assert missing.status_code == 401
    assert ok.status_code == 200
    assert ok.json() == {"authorized": True}


def test_admin_org_create_list_delete_round_trip(isolated_org_db, admin_token_env):
    from app.main import app

    admin_token_env("admin-secret")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-secret"}

    created = client.post("/admin/v1/orgs", json={"name": "Acme"}, headers=headers)
    listed = client.get("/admin/v1/orgs", headers=headers)
    deleted = client.delete("/admin/v1/orgs/acme", headers=headers)

    assert created.status_code == 201
    assert created.json()["slug"] == "acme"
    assert listed.status_code == 200
    assert [item["slug"] for item in listed.json()] == ["acme"]
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "departments_removed": 0}
