"""add pipeline role system prompt overrides

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-08-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_llm_configs", sa.Column("enricher_system_prompt", sa.Text(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("normalizer_system_prompt", sa.Text(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("validator_system_prompt", sa.Text(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("validator_image_system_prompt", sa.Text(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("adjuster_system_prompt", sa.Text(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("generalizer_system_prompt", sa.Text(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("local_model_system_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "local_model_system_prompt")
    op.drop_column("workspace_llm_configs", "generalizer_system_prompt")
    op.drop_column("workspace_llm_configs", "adjuster_system_prompt")
    op.drop_column("workspace_llm_configs", "validator_image_system_prompt")
    op.drop_column("workspace_llm_configs", "validator_system_prompt")
    op.drop_column("workspace_llm_configs", "normalizer_system_prompt")
    op.drop_column("workspace_llm_configs", "enricher_system_prompt")
