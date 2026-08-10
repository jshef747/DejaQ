"""add pipeline role model overrides

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_llm_configs", sa.Column("generalizer_model", sa.String(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("adjuster_model", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "adjuster_model")
    op.drop_column("workspace_llm_configs", "generalizer_model")
