"""e5f6a7b8c9d0 restores the unique constraint the workspace rename dropped.

The table has been running without it, so the rebuild's row copy can meet
duplicates it cannot insert. Every such row is an encrypted provider API key,
so the migration refuses to choose one to drop and aborts naming them instead.
"""
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.no_model

SERVER_DIR = Path(__file__).resolve().parents[1]

_INSERT = (
    "INSERT INTO workspace_provider_credentials "
    "(workspace_id, provider, encrypted_key, created_at, updated_at) "
    "VALUES (:workspace_id, :provider, :key, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
)


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _seed(db_path: Path, rows: list[tuple[int, str, str]]) -> None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT OR IGNORE INTO workspaces (id, name, slug) VALUES (1, 'A', 'a')"))
        for workspace_id, provider, key in rows:
            conn.execute(
                sa.text(_INSERT),
                {"workspace_id": workspace_id, "provider": provider, "key": key},
            )
    engine.dispose()


def test_duplicate_credentials_abort_the_migration_naming_them(tmp_path):
    db_path = tmp_path / "dupes.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "d2e3f4a5b6c7")
    _seed(db_path, [(1, "openai", "cipher-one"), (1, "openai", "cipher-two")])

    with pytest.raises(RuntimeError) as excinfo:
        command.upgrade(cfg, "e5f6a7b8c9d0")

    message = str(excinfo.value)
    assert "workspace_id=1" in message
    assert "openai" in message
    # Both keys survive: the operator, not the migration, decides which goes.
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        keys = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT encrypted_key FROM workspace_provider_credentials")
            )
        }
    engine.dispose()
    assert keys == {"cipher-one", "cipher-two"}


def test_clean_database_upgrades_and_then_rejects_duplicates(tmp_path):
    db_path = tmp_path / "clean.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "d2e3f4a5b6c7")
    _seed(db_path, [(1, "openai", "cipher-one"), (1, "anthropic", "cipher-two")])

    command.upgrade(cfg, "e5f6a7b8c9d0")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        providers = {
            row[0]
            for row in conn.execute(sa.text("SELECT provider FROM workspace_provider_credentials"))
        }
    assert providers == {"openai", "anthropic"}
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                sa.text(_INSERT),
                {"workspace_id": 1, "provider": "openai", "key": "cipher-three"},
            )
    engine.dispose()
