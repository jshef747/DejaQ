"""add classifier_choice and legacy_routing_threshold

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-08-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_llm_configs", sa.Column("classifier_choice", sa.String(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("legacy_routing_threshold", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "legacy_routing_threshold")
    op.drop_column("workspace_llm_configs", "classifier_choice")
