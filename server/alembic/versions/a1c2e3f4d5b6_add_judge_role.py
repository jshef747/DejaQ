"""add judge_model and judge_system_prompt override columns

Revision ID: a1c2e3f4d5b6
Revises: f9e8d7c6b5a4
Create Date: 2026-09-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a1c2e3f4d5b6"
down_revision = "f9e8d7c6b5a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_llm_configs", sa.Column("judge_model", sa.String(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("judge_system_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "judge_system_prompt")
    op.drop_column("workspace_llm_configs", "judge_model")
