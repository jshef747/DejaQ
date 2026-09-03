"""restore the departments (workspace_id, slug) unique constraint

Revision ID: b7c8d9e0f1a2
Revises: a1c2e3f4d5b6
Create Date: 2026-09-03 00:00:00.000000

The department model declares a unique constraint on (workspace_id, slug),
`uq_dept_workspace_slug`. The workspace rename migration (d1e2f3a4b5c6)
dropped its predecessor `uq_dept_org_slug` and recreated the constraint under
the new name inside a `batch_alter_table(recreate="always")`, but the batch
rebuild lost it and no later migration restored it. An alembic-built (i.e.
production) database therefore has no unique index on departments at all, so
`dept_repo.create_dept` - which relied on catching the DB IntegrityError -
silently accepts duplicate departments. The test suite builds its schema with
`Base.metadata.create_all`, which does include the constraint, so it never saw
this. This is the exact twin of the credentials bug e5f6a7b8c9d0 fixed.

Unlike a provider credential, a duplicate department carries no irreplaceable
secret and both duplicates point at the same cache_namespace, so this
migration de-duplicates automatically instead of aborting: it keeps the oldest
row (lowest id) per (workspace_id, slug) and deletes the rest, logging exactly
which ids it removed, then rebuilds the table with the unique constraint in
place.
"""
import logging

from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "a1c2e3f4d5b6"
branch_labels = None
depends_on = None

_UNIQUE_NAME = "uq_dept_workspace_slug"

logger = logging.getLogger("alembic.runtime.migration")


def _dedupe_departments() -> None:
    bind = op.get_bind()
    # Keep the oldest row (lowest id) per (workspace_id, slug); the rest are
    # duplicates the missing constraint let in.
    stale = (
        bind.execute(
            sa.text(
                "SELECT id, workspace_id, slug FROM departments WHERE id NOT IN ("
                "  SELECT MIN(id) FROM departments GROUP BY workspace_id, slug"
                ") ORDER BY id"
            )
        )
        .fetchall()
    )
    if not stale:
        return
    for row in stale:
        logger.warning(
            "Removing duplicate department id=%s (workspace_id=%s slug='%s') - "
            "kept the oldest row with the same (workspace_id, slug).",
            row.id,
            row.workspace_id,
            row.slug,
        )
    ids = [row.id for row in stale]
    bind.execute(
        sa.text("DELETE FROM departments WHERE id IN :ids").bindparams(
            sa.bindparam("ids", ids, expanding=True)
        )
    )


def upgrade() -> None:
    _dedupe_departments()
    with op.batch_alter_table("departments", recreate="always") as batch_op:
        batch_op.create_unique_constraint(_UNIQUE_NAME, ["workspace_id", "slug"])


def downgrade() -> None:
    with op.batch_alter_table("departments", recreate="always") as batch_op:
        batch_op.drop_constraint(_UNIQUE_NAME, type_="unique")
