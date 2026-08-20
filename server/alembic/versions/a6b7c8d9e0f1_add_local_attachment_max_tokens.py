"""add local_attachment_max_tokens override

Revision ID: a6b7c8d9e0f1
Revises: f7a8b9c0d1e2
Create Date: 2026-08-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a6b7c8d9e0f1"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_llm_configs", sa.Column("local_attachment_max_tokens", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "local_attachment_max_tokens")
