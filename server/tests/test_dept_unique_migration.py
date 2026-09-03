"""b7c8d9e0f1a2 restores the (workspace_id, slug) unique constraint the
workspace rename dropped from departments.

The suite normally builds its schema with `Base.metadata.create_all`, which
includes the constraint the migration chain omitted - so only a DB built via
`alembic upgrade head` exercises the production schema. This test does that and
asserts the duplicate is rejected, and that pre-existing duplicates are
de-duped (oldest kept) rather than aborting the migration.
"""
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.no_model

SERVER_DIR = Path(__file__).resolve().parents[1]

_INSERT = (
    "INSERT INTO departments "
    "(id, workspace_id, name, slug, cache_namespace, created_at) "
    "VALUES (:id, :workspace_id, :name, :slug, :ns, '2026-01-01 00:00:00')"
)


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _seed_workspace(db_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT OR IGNORE INTO workspaces (id, name, slug) VALUES (1, 'A', 'acme')"))
    engine.dispose()


def test_head_schema_rejects_duplicate_departments(tmp_path):
    db_path = tmp_path / "clean.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "head")
    _seed_workspace(db_path)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(sa.text(_INSERT), {"id": 1, "workspace_id": 1, "name": "Sales", "slug": "sales", "ns": "acme__sales"})
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(sa.text(_INSERT), {"id": 2, "workspace_id": 1, "name": "Sales", "slug": "sales", "ns": "acme__sales"})
    engine.dispose()


def test_preexisting_duplicates_are_deduped_keeping_oldest(tmp_path):
    db_path = tmp_path / "dupes.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "a1c2e3f4d5b6")  # before the constraint restore
    _seed_workspace(db_path)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for i in (1, 2, 3):
            conn.execute(
                sa.text(_INSERT),
                {"id": i, "workspace_id": 1, "name": "Sales", "slug": "sales", "ns": "acme__sales"},
            )
    engine.dispose()

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM departments ORDER BY id"))]
    engine.dispose()
    assert ids == [1]  # oldest kept, duplicates removed
