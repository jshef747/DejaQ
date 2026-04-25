import inspect
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient


PARITY_ROWS = [
    ("org list", ("org", "list"), ["admin_service.list_orgs"], ("GET", "/admin/v1/orgs")),
    ("org create", ("org", "create"), ["admin_service.create_org"], ("POST", "/admin/v1/orgs")),
    (
        "org delete",
        ("org", "delete"),
        ["admin_service.list_departments", "admin_service.delete_org"],
        ("DELETE", "/admin/v1/orgs/{slug}"),
    ),
    (
        "dept list",
        ("dept", "list"),
        ["admin_service.list_departments"],
        ("GET", "/admin/v1/departments"),
    ),
    (
        "dept create",
        ("dept", "create"),
        ["admin_service.create_department"],
        ("POST", "/admin/v1/orgs/{org_slug}/departments"),
    ),
    (
        "dept delete",
        ("dept", "delete"),
        ["admin_service.list_departments", "admin_service.delete_department"],
        ("DELETE", "/admin/v1/orgs/{org_slug}/departments/{dept_slug}"),
    ),
    (
        "key list",
        ("key", "list"),
        ["admin_service.list_keys"],
        ("GET", "/admin/v1/orgs/{org_slug}/keys"),
    ),
    (
        "key generate",
        ("key", "generate"),
        ["admin_service.generate_key"],
        ("POST", "/admin/v1/orgs/{org_slug}/keys"),
    ),
    (
        "key revoke",
        ("key", "revoke"),
        ["admin_service.revoke_key"],
        ("DELETE", "/admin/v1/keys/{key_id}"),
    ),
    (
        "stats",
        ("stats",),
        ["stats_service.org_stats", "stats_service.department_stats"],
        ("GET", "/admin/v1/stats/orgs"),
    ),
    (
        "stats departments",
        ("stats",),
        ["stats_service.org_stats", "stats_service.department_stats"],
        ("GET", "/admin/v1/stats/orgs/{org_slug}/departments"),
    ),
]


API_ONLY_ROWS = [
    ("llm config read", "llm_config_service.read_for_org", ("GET", "/admin/v1/orgs/{org_slug}/llm-config")),
    ("llm config update", "llm_config_service.update_for_org", ("PUT", "/admin/v1/orgs/{org_slug}/llm-config")),
    ("feedback list", "feedback_service.list_feedback", ("GET", "/admin/v1/feedback")),
    ("feedback submit", "feedback_service.submit_feedback", ("POST", "/admin/v1/feedback")),
]


def _client(admin_token_env):
    from app.main import app

    admin_token_env("admin-secret")
    return TestClient(app), {"Authorization": "Bearer admin-secret"}


def _click_command(path):
    from cli import admin

    command = admin.cli
    for part in path:
        command = command.commands[part]
    return command


def _route(method: str, path: str):
    from app.main import app

    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route
    raise AssertionError(f"Missing route: {method} {path}")


def _source_for_click(path) -> str:
    source = inspect.getsource(_click_command(path).callback)
    if path == ("stats",):
        from cli import stats

        source += "\n" + inspect.getsource(stats.run)
    return source


def _seed_requests(db_path, rows):
    con = sqlite3.connect(db_path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            org TEXT NOT NULL,
            department TEXT NOT NULL,
            latency_ms INTEGER NOT NULL,
            cache_hit INTEGER NOT NULL,
            difficulty TEXT,
            model_used TEXT,
            response_id TEXT
        )"""
    )
    con.executemany(
        "INSERT INTO requests (ts, org, department, latency_ms, cache_hit, difficulty, model_used, response_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()


@pytest.mark.parametrize(("name", "click_path", "service_refs", "route_ref"), PARITY_ROWS)
def test_parity_matrix_leaf_click_commands_map_to_services_and_routes(
    name,
    click_path,
    service_refs,
    route_ref,
):
    source = _source_for_click(click_path)
    route = _route(*route_ref)
    route_source = inspect.getsource(route.endpoint)

    for service_ref in service_refs:
        assert service_ref in source, name

    service_modules = {ref.split(".")[0] for ref in service_refs}
    service_functions = {ref.split(".")[1] for ref in service_refs}
    assert any(module in route_source for module in service_modules), name
    assert any(function in route_source for function in service_functions), name


@pytest.mark.parametrize(("name", "service_ref", "route_ref"), API_ONLY_ROWS)
def test_parity_matrix_api_only_rows_map_to_shared_services(name, service_ref, route_ref):
    route_source = inspect.getsource(_route(*route_ref).endpoint)
    module_name, function_name = service_ref.split(".")

    assert module_name in route_source, name
    assert function_name in route_source, name


def test_org_department_duplicate_and_delete_behaviors_match_service_and_api(
    isolated_org_db,
    admin_token_env,
):
    from app.services import admin_service

    client, headers = _client(admin_token_env)

    admin_service.create_org("Service Org")
    with pytest.raises(admin_service.DuplicateSlug) as org_exc:
        admin_service.create_org("Service Org")
    assert org_exc.value.slug == "service-org"

    api_org = client.post("/admin/v1/orgs", json={"name": "API Org"}, headers=headers)
    api_org_duplicate = client.post("/admin/v1/orgs", json={"name": "API Org"}, headers=headers)
    assert api_org.status_code == 201
    assert api_org_duplicate.status_code == 409

    admin_service.create_department("service-org", "Support")
    with pytest.raises(admin_service.DuplicateSlug) as dept_exc:
        admin_service.create_department("service-org", "Support")
    assert dept_exc.value.slug == "support"

    api_dept = client.post(
        "/admin/v1/orgs/api-org/departments",
        json={"name": "Support"},
        headers=headers,
    )
    api_dept_duplicate = client.post(
        "/admin/v1/orgs/api-org/departments",
        json={"name": "Support"},
        headers=headers,
    )
    assert api_dept.status_code == 201
    assert api_dept_duplicate.status_code == 409

    service_dept_deleted = admin_service.delete_department("service-org", "support")
    assert service_dept_deleted.model_dump() == {
        "deleted": True,
        "cache_namespace": "service-org__support",
    }

    api_dept_deleted = client.delete(
        "/admin/v1/orgs/api-org/departments/support",
        headers=headers,
    )
    assert api_dept_deleted.json() == {
        "deleted": True,
        "cache_namespace": "api-org__support",
    }

    admin_service.create_department("service-org", "Eng")
    service_org_deleted = admin_service.delete_org("service-org")
    assert service_org_deleted.model_dump() == {
        "deleted": True,
        "departments_removed": 1,
    }

    client.post("/admin/v1/orgs", json={"name": "API Delete"}, headers=headers)
    client.post("/admin/v1/orgs/api-delete/departments", json={"name": "Eng"}, headers=headers)
    api_org_deleted = client.delete("/admin/v1/orgs/api-delete", headers=headers)
    assert api_org_deleted.json() == {
        "deleted": True,
        "departments_removed": 1,
    }


def test_key_generate_force_revoke_and_token_visibility_match_service_and_api(
    isolated_org_db,
    admin_token_env,
):
    from app.services import admin_service

    client, headers = _client(admin_token_env)

    admin_service.create_org("Service Keys")
    first = admin_service.generate_key("service-keys", force=False)
    with pytest.raises(admin_service.ActiveKeyExists) as active_exc:
        admin_service.generate_key("service-keys", force=False)
    second = admin_service.generate_key("service-keys", force=True)
    listed = admin_service.list_keys("service-keys")
    revoked = admin_service.revoke_key(second.id)
    revoked_again = admin_service.revoke_key(second.id)

    assert active_exc.value.key_id == first.id
    assert second.id != first.id
    assert {item.token_prefix for item in listed} == {
        first.token[:12] + "...",
        second.token[:12] + "...",
    }
    assert all(not hasattr(item, "token") for item in listed)
    assert revoked.already_revoked is False
    assert revoked_again.already_revoked is True

    client.post("/admin/v1/orgs", json={"name": "API Keys"}, headers=headers)
    api_first = client.post("/admin/v1/orgs/api-keys/keys", headers=headers)
    api_conflict = client.post("/admin/v1/orgs/api-keys/keys", headers=headers)
    api_second = client.post("/admin/v1/orgs/api-keys/keys?force=true", headers=headers)
    api_listed = client.get("/admin/v1/orgs/api-keys/keys", headers=headers)
    api_revoked = client.delete(f"/admin/v1/keys/{api_second.json()['id']}", headers=headers)
    api_revoked_again = client.delete(f"/admin/v1/keys/{api_second.json()['id']}", headers=headers)

    assert api_first.status_code == 201
    assert "token" in api_first.json()
    assert api_conflict.status_code == 409
    assert api_second.status_code == 201
    assert "token" in api_second.json()
    assert api_listed.status_code == 200
    assert all("token" not in item for item in api_listed.json())
    assert all(item["token_prefix"].endswith("...") for item in api_listed.json())
    assert api_revoked.json()["already_revoked"] is False
    assert api_revoked_again.json()["already_revoked"] is True


def test_stats_windows_match_service_and_api(
    isolated_org_db,
    isolated_stats_db,
    admin_token_env,
):
    from app.services import admin_service, stats_service

    client, headers = _client(admin_token_env)
    admin_service.create_org("Acme")
    admin_service.create_department("acme", "Eng")
    _seed_requests(
        isolated_stats_db,
        [
            ("2026-03-31T23:59:59+00:00", "acme", "eng", 50, 1, "easy", "before", "r0"),
            ("2026-04-01T00:00:00+00:00", "acme", "eng", 100, 1, "easy", "cache", "r1"),
            ("2026-04-14T23:59:59+00:00", "acme", "eng", 200, 0, "hard", "gemini", "r2"),
            ("2026-04-15T00:00:00+00:00", "acme", "eng", 300, 1, "easy", "after", "r3"),
        ],
    )

    service_orgs = stats_service.org_stats(
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 15),
    )
    service_depts = stats_service.department_stats(
        "acme",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 15),
    )
    api_orgs = client.get(
        "/admin/v1/stats/orgs?from=2026-04-01&to=2026-04-15",
        headers=headers,
    )
    api_depts = client.get(
        "/admin/v1/stats/orgs/acme/departments?from=2026-04-01&to=2026-04-15",
        headers=headers,
    )
    reversed_range = client.get(
        "/admin/v1/stats/orgs?from=2026-04-15&to=2026-04-01",
        headers=headers,
    )

    assert api_orgs.status_code == 200
    assert api_depts.status_code == 200
    assert api_orgs.json() == service_orgs.model_dump(mode="json")
    assert api_depts.json() == service_depts.model_dump(mode="json")
    assert api_orgs.json()["total"]["requests"] == 2
    assert api_depts.json()["items"][0]["models_used"] == ["cache", "gemini"]
    assert reversed_range.status_code == 422
