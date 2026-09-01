"""add attachment_routing override map

Revision ID: f9e8d7c6b5a4
Revises: d4e5f6a7b8c9
Create Date: 2026-09-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f9e8d7c6b5a4"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_llm_configs", sa.Column("attachment_routing", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "attachment_routing")
