"""add external_provider column and backfill from external_model

Revision ID: d2e3f4a5b6c7
Revises: c6d7e8f9a0b1
Create Date: 2026-08-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

from app.services.provider_inference import provider_for_model


revision = "d2e3f4a5b6c7"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_llm_configs", sa.Column("external_provider", sa.String(), nullable=True))

    bind = op.get_bind()
    configs_table = sa.table(
        "workspace_llm_configs",
        sa.column("workspace_id", sa.Integer()),
        sa.column("external_model", sa.String()),
        sa.column("external_provider", sa.String()),
    )
    rows = bind.execute(
        sa.select(configs_table.c.workspace_id, configs_table.c.external_model).where(
            configs_table.c.external_model.isnot(None)
        )
    ).fetchall()
    for workspace_id, external_model in rows:
        try:
            provider = provider_for_model(external_model)
        except ValueError:
            continue
        bind.execute(
            configs_table.update()
            .where(configs_table.c.workspace_id == workspace_id)
            .values(external_provider=provider)
        )


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "external_provider")
