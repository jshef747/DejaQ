"""add per-workspace alternative-draft settings

Revision ID: b8c9d0e1f2a3
Revises: d4e5f6a7b8c9
Create Date: 2026-08-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b8c9d0e1f2a3"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All nullable: NULL means "no override, use the shipped default" (see
    # CACHE_DRAFTS_* in app/config.py), which is how every other per-workspace
    # override on this table behaves. No server_default for the same reason - a
    # default here would make every existing workspace look like it had
    # explicitly opted into a feature that ships off.
    op.add_column("workspace_llm_configs", sa.Column("drafts_enabled", sa.Boolean(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("drafts_max_distance", sa.Float(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("drafts_max_delta", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "drafts_max_delta")
    op.drop_column("workspace_llm_configs", "drafts_max_distance")
    op.drop_column("workspace_llm_configs", "drafts_enabled")
