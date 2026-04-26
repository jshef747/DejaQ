from datetime import datetime, timezone
import sqlite3

from click.testing import CliRunner
from pydantic import BaseModel


class _Org(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime


def test_org_list_uses_admin_service(monkeypatch):
    from cli import admin

    calls = []

    def _list_orgs(ctx=None):
        calls.append("list")
        return [
            _Org(
                id=1,
                name="Acme",
                slug="acme",
                created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            )
        ]

    monkeypatch.setattr(admin.admin_service, "list_orgs", _list_orgs)

    result = CliRunner().invoke(admin.cli, ["org", "list"])

    assert result.exit_code == 0
    assert calls == ["list"]
    assert "Acme" in result.output


def test_cli_smoke_flow_uses_shared_services(isolated_org_db, isolated_stats_db, monkeypatch):
    from app.services import stats_service
    from app.services import admin_service
    from cli import admin
    from cli import stats as cli_stats

    con = sqlite3.connect(isolated_stats_db)
    con.execute(
        """CREATE TABLE requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, org TEXT NOT NULL, department TEXT NOT NULL,
            latency_ms INTEGER NOT NULL, cache_hit INTEGER NOT NULL,
            difficulty TEXT, model_used TEXT, response_id TEXT
        )"""
    )
    con.execute(
        "INSERT INTO requests (ts, org, department, latency_ms, cache_hit, difficulty, model_used, response_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-04-01T00:00:00+00:00", "acme", "eng", 100, 1, "easy", "cache", "r1"),
    )
    con.commit()
    con.close()

    calls = []
    original_list_keys = admin_service.list_keys

    def _wrap(name, target):
        def _wrapped(*args, **kwargs):
            calls.append(name)
            return target(*args, **kwargs)

        return _wrapped

    monkeypatch.setattr(admin.admin_service, "create_org", _wrap("create_org", admin_service.create_org))
    monkeypatch.setattr(admin.admin_service, "list_orgs", _wrap("list_orgs", admin_service.list_orgs))
    monkeypatch.setattr(admin.admin_service, "create_department", _wrap("create_department", admin_service.create_department))
    monkeypatch.setattr(admin.admin_service, "list_departments", _wrap("list_departments", admin_service.list_departments))
    monkeypatch.setattr(admin.admin_service, "generate_key", _wrap("generate_key", admin_service.generate_key))
    monkeypatch.setattr(admin.admin_service, "list_keys", _wrap("list_keys", admin_service.list_keys))
    monkeypatch.setattr(admin.admin_service, "revoke_key", _wrap("revoke_key", admin_service.revoke_key))
    monkeypatch.setattr(admin.admin_service, "delete_department", _wrap("delete_department", admin_service.delete_department))
    monkeypatch.setattr(admin.admin_service, "delete_org", _wrap("delete_org", admin_service.delete_org))
    monkeypatch.setattr(cli_stats.stats_service, "org_stats", _wrap("org_stats", stats_service.org_stats))
    monkeypatch.setattr(cli_stats.stats_service, "department_stats", _wrap("department_stats", stats_service.department_stats))
    monkeypatch.setattr(cli_stats, "_print_cache_health", lambda *_args: None)

    runner = CliRunner()

    def _invoke_ok(args, input=None):
        result = runner.invoke(admin.cli, args, input=input)
        assert result.exit_code == 0, result.output
        return result.output

    org_create = _invoke_ok(["org", "create", "--name", "Acme"])
    assert "Organization created" in org_create
    assert "Acme" in org_create
    assert "acme" in org_create

    org_list = _invoke_ok(["org", "list"])
    assert "Organizations" in org_list
    assert "Acme" in org_list
    assert "acme" in org_list

    dept_create = _invoke_ok(["dept", "create", "--org", "acme", "--name", "Eng"])
    assert "Department created" in dept_create
    assert "Eng" in dept_create
    assert "acme__eng" in dept_create

    dept_list = _invoke_ok(["dept", "list", "--org", "acme"])
    assert "Departments" in dept_list
    assert "Eng" in dept_list
    assert "acme__eng" in dept_list

    key_generate = _invoke_ok(["key", "generate", "--org", "acme"])
    assert "API key generated" in key_generate
    assert "org" in key_generate
    assert "acme" in key_generate
    assert "token" in key_generate

    key_list = _invoke_ok(["key", "list", "--org", "acme"])
    assert "API Keys" in key_list
    assert "acme" in key_list
    assert "..." in key_list

    from app.dependencies.management_auth import ManagementAuthContext
    key_id = original_list_keys("acme", ctx=ManagementAuthContext.system())[0].id
    key_revoke = _invoke_ok(["key", "revoke", "--id", str(key_id)])
    assert f"Key id={key_id} revoked" in key_revoke

    stats = _invoke_ok(["stats"])
    assert "DejaQ Usage Stats" in stats
    assert "acme" in stats
    assert "eng" in stats
    assert "100.0%" in stats
    assert "cache" in stats

    dept_delete = _invoke_ok(
        ["dept", "delete", "--org", "acme", "--slug", "eng"],
        input="y\n",
    )
    assert "Delete department" in dept_delete
    assert "Department eng deleted" in dept_delete
    assert "Freed namespace: acme__eng" in dept_delete

    org_delete = _invoke_ok(
        ["org", "delete", "--slug", "acme"],
        input="y\n",
    )
    assert "Organization acme deleted" in org_delete

    assert calls == [
        "create_org",
        "list_orgs",
        "create_department",
        "list_departments",
        "generate_key",
        "list_keys",
        "revoke_key",
        "org_stats",
        "department_stats",
        "list_departments",
        "delete_department",
        "list_departments",
        "delete_org",
    ]
