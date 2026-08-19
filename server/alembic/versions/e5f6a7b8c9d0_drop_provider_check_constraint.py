"""drop the credentials provider CHECK constraint

Revision ID: e5f6a7b8c9d0
Revises: d2e3f4a5b6c7
Create Date: 2026-08-19 00:00:00.000000

The registry (`app.services.provider_registry`) is now the single source of
truth for valid provider names; this per-name CHECK constraint duplicated it,
so every new provider cost a full SQLite table rebuild.

On a database migrated from scratch through this history, the constraint's
real name is `ck_org_provider_credentials_provider` - it was never renamed by
d1e2f3a4b5c6 (rename organizations to workspaces), unlike every other
constraint that migration touched. The model's `ck_workspace_provider_credentials_provider`
was never the name actually on disk; verified by building a fresh database
through alembic head and reading `sqlite_master`.

That same check turned up a second, more serious drift: the unique
constraint on (workspace_id, provider) - `uq_org_provider_credentials_org_provider`,
explicitly dropped and recreated as `uq_workspace_provider_credentials_workspace_provider`
inside that same d1e2f3a4b5c6 batch - does not survive the batch rebuild.
A from-scratch database has no unique constraint on this table at all today
(confirmed by inserting two rows with the same (workspace_id, provider) and
finding the DB accepts the duplicate). This migration restores it while it is
already rebuilding the table for the CHECK removal.
"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None

_UNIQUE_NAME = "uq_workspace_provider_credentials_workspace_provider"
_CHECK_NAME = "ck_org_provider_credentials_provider"


def upgrade() -> None:
    with op.batch_alter_table("workspace_provider_credentials", recreate="always") as batch_op:
        batch_op.drop_constraint(_CHECK_NAME, type_="check")
        batch_op.create_unique_constraint(_UNIQUE_NAME, ["workspace_id", "provider"])


def downgrade() -> None:
    with op.batch_alter_table("workspace_provider_credentials", recreate="always") as batch_op:
        batch_op.drop_constraint(_UNIQUE_NAME, type_="unique")
        batch_op.create_check_constraint(
            _CHECK_NAME,
            "provider IN ('google', 'openai', 'anthropic', 'mistral', 'cohere', 'together', 'groq', 'fireworks')",
        )
