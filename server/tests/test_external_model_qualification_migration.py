"""f7a8b9c0d1e2 qualifies every stored external_model with its LiteLLM
provider prefix, unconditionally - even when the model already contains a
slash. `groq/compound` must become `groq/groq/compound`, not `groq/compound`
(litellm.get_llm_provider("groq/compound") returns model "compound", the
wrong model name on the wire; only the double-qualified form round-trips to
"groq/compound").

A row with no recorded external_provider gets one shot at d2e3f4a5b6c7's own
frozen prefix guess; a model the guess cannot place is left unqualified and
untouched rather than guessed at.
"""
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.no_model

SERVER_DIR = Path(__file__).resolve().parents[1]

# workspace_id -> (name, external_model, external_provider)
_ROWS = {
    1: ("google", "gemini-2.5-flash", "google"),
    2: ("openai", "gpt-4o-mini", "openai"),
    3: ("anthropic", "claude-sonnet-5", "anthropic"),
    4: ("xai", "grok-4.5", "xai"),
    5: ("deepseek", "deepseek-v4-pro", "deepseek"),
    6: ("groq", "groq-compound-mini", "groq"),
    7: ("groq-slashed-compound", "groq/compound", "groq"),
    8: ("groq-slashed-gpt-oss", "openai/gpt-oss-120b", "groq"),
    9: ("guessable", "claude-opus-5", None),
    10: ("unplaceable", "grok-4.6", None),
}


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _seed(db_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for workspace_id, (slug, _model, _provider) in _ROWS.items():
            conn.execute(
                sa.text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :slug, :slug)"),
                {"id": workspace_id, "slug": slug},
            )
        for workspace_id, (_slug, model, provider) in _ROWS.items():
            conn.execute(
                sa.text(
                    "INSERT INTO workspace_llm_configs (workspace_id, external_model, external_provider) "
                    "VALUES (:workspace_id, :model, :provider)"
                ),
                {"workspace_id": workspace_id, "model": model, "provider": provider},
            )
    engine.dispose()


def _read_rows(db_path: Path) -> dict[int, tuple[str, str | None]]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        rows = {
            workspace_id: (external_model, external_provider)
            for workspace_id, external_model, external_provider in conn.execute(
                sa.text(
                    "SELECT workspace_id, external_model, external_provider "
                    "FROM workspace_llm_configs"
                )
            )
        }
    engine.dispose()
    return rows


def test_qualify_backfill_and_downgrade_round_trip(tmp_path):
    db_path = tmp_path / "qualify.db"
    cfg = _alembic_config(db_path)

    command.upgrade(cfg, "e5f6a7b8c9d0")
    _seed(db_path)

    command.upgrade(cfg, "f7a8b9c0d1e2")
    after = _read_rows(db_path)

    assert after[1] == ("gemini/gemini-2.5-flash", "google")
    assert after[2] == ("openai/gpt-4o-mini", "openai")
    assert after[3] == ("anthropic/claude-sonnet-5", "anthropic")
    assert after[4] == ("xai/grok-4.5", "xai")
    assert after[5] == ("deepseek/deepseek-v4-pro", "deepseek")
    assert after[6] == ("groq/groq-compound-mini", "groq")

    # The trap: unconditional prefixing even when the stored model already
    # contains a slash. A naive `if "/" not in model` guard would leave these
    # two exactly as measured-wrong: "groq/compound" (routes to model
    # "compound") and "openai/gpt-oss-120b" (routes to OpenAI, not Groq).
    assert after[7] == ("groq/groq/compound", "groq")
    assert after[7][0] != "groq/compound"
    assert after[8] == ("groq/openai/gpt-oss-120b", "groq")

    # Null provider, guessable by d2e3f4a5b6c7's frozen prefix rule: placed
    # AND external_provider backfilled (no more request-time guessing exists
    # after this stage, so a qualified model with a still-null provider would
    # 422 on every hard query).
    assert after[9] == ("anthropic/claude-opus-5", "anthropic")

    # Null provider, unplaceable by the frozen guess: left alone rather than
    # guessed. Becomes a clear 422 at request time instead of a silent
    # misroute.
    assert after[10] == ("grok-4.6", None)

    command.downgrade(cfg, "e5f6a7b8c9d0")
    restored = _read_rows(db_path)

    for workspace_id, (_slug, original_model, _provider) in _ROWS.items():
        assert restored[workspace_id][0] == original_model, workspace_id
