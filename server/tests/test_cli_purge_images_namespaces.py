from datetime import datetime, timezone
from types import SimpleNamespace

from click.testing import CliRunner
from pydantic import BaseModel


class _Dept(BaseModel):
    id: int
    workspace_slug: str
    name: str
    slug: str
    cache_namespace: str
    created_at: datetime


def _dept(workspace_slug: str, slug: str) -> _Dept:
    return _Dept(
        id=1,
        workspace_slug=workspace_slug,
        name=slug,
        slug=slug,
        cache_namespace=f"{workspace_slug}__{slug}",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _fake_memory_service(namespaces_seen: list[str]):
    def get_memory_service(namespace: str):
        namespaces_seen.append(namespace)
        return SimpleNamespace(image_entry_ids=lambda: [])

    return get_memory_service


def test_purge_images_includes_default_namespace_alongside_departments(monkeypatch):
    """Requests with no X-DejaQ-Department header always land in
    '<workspace>--default' (app/middleware/api_key.py), even when the
    workspace has departments — the purge must not skip it."""
    from cli import admin

    monkeypatch.setattr(
        admin.admin_service, "list_departments",
        lambda workspace_slug, ctx=None: [_dept("acme", "eng")],
    )
    namespaces_seen: list[str] = []
    monkeypatch.setattr(
        "app.services.memory_chromaDB.get_memory_service", _fake_memory_service(namespaces_seen)
    )

    result = CliRunner().invoke(admin.cli, ["cache", "purge-images", "--workspace", "acme"])

    assert result.exit_code == 0, result.output
    assert "acme--default" in namespaces_seen
    assert "acme__eng" in namespaces_seen


def test_purge_images_scoped_to_one_department_skips_default(monkeypatch):
    from cli import admin

    monkeypatch.setattr(
        admin.admin_service, "list_departments",
        lambda workspace_slug, ctx=None: [_dept("acme", "eng")],
    )
    namespaces_seen: list[str] = []
    monkeypatch.setattr(
        "app.services.memory_chromaDB.get_memory_service", _fake_memory_service(namespaces_seen)
    )

    result = CliRunner().invoke(
        admin.cli, ["cache", "purge-images", "--workspace", "acme", "--department", "eng"]
    )

    assert result.exit_code == 0, result.output
    assert namespaces_seen == ["acme__eng"]
