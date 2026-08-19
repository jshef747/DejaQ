from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.no_model

SERVER_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_backfill_recognized_and_unrecognized_models(tmp_path):
    db_path = tmp_path / "backfill.db"
    cfg = _alembic_config(db_path)

    # Land on the revision just before this one, seed data, then run this migration.
    command.upgrade(cfg, "c6d7e8f9a0b1")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO workspaces (id, name, slug) VALUES (1, 'A', 'a'), (2, 'B', 'b')")
        )
        conn.execute(
            sa.text(
                "INSERT INTO workspace_llm_configs (workspace_id, external_model) "
                "VALUES (1, 'claude-sonnet-5'), (2, 'llama-3.3-70b')"
            )
        )
    engine.dispose()

    command.upgrade(cfg, "d2e3f4a5b6c7")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        rows = dict(
            conn.execute(
                sa.text("SELECT workspace_id, external_provider FROM workspace_llm_configs")
            ).fetchall()
        )
    engine.dispose()

    assert rows[1] == "anthropic"
    assert rows[2] is None
