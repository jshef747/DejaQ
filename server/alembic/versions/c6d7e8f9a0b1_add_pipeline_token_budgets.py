"""add per-workspace token budget overrides

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-08-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_llm_configs", sa.Column("default_max_tokens", sa.Integer(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("rewrite_max_tokens", sa.Integer(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("ollama_num_ctx", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "ollama_num_ctx")
    op.drop_column("workspace_llm_configs", "rewrite_max_tokens")
    op.drop_column("workspace_llm_configs", "default_max_tokens")
