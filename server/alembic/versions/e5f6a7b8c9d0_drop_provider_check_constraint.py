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

Because the table has been running without that unique constraint, a database
may already hold duplicate (workspace_id, provider) rows, which the rebuild's
row copy would reject with an opaque IntegrityError. Every such row is an
encrypted provider API key, so `upgrade()` refuses to pick one to drop: it
checks first and aborts naming the offending rows, leaving the operator to
delete the unwanted credential through the admin API and re-run.

The downgrade restores the CHECK constraint with its pre-stage-2 provider
list, so it fails the same way on a database that has since stored an `xai`
or `deepseek` credential - delete those rows first, or stay on this revision.
"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None

_UNIQUE_NAME = "uq_workspace_provider_credentials_workspace_provider"
_CHECK_NAME = "ck_org_provider_credentials_provider"


def _reject_duplicate_credentials() -> None:
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT workspace_id, provider, COUNT(*) AS row_count "
                "FROM workspace_provider_credentials "
                "GROUP BY workspace_id, provider HAVING COUNT(*) > 1"
            )
        )
        .fetchall()
    )
    if not duplicates:
        return
    offenders = "; ".join(
        f"workspace_id={row.workspace_id} provider='{row.provider}' ({row.row_count} rows)"
        for row in duplicates
    )
    raise RuntimeError(
        "workspace_provider_credentials holds duplicate (workspace_id, provider) rows, "
        "so the unique constraint this migration restores cannot be created: "
        f"{offenders}. Each of those rows is an encrypted provider API key, so this "
        "migration will not choose one to delete. Remove the unwanted credential via "
        "DELETE /admin/v1/workspaces/{slug}/credentials/{provider} (re-adding the key "
        "you want to keep afterwards), then re-run `alembic upgrade head`."
    )


def upgrade() -> None:
    _reject_duplicate_credentials()
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
