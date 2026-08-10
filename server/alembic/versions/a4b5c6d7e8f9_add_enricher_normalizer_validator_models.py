"""add enricher, normalizer, validator pipeline role model overrides

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-08-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_llm_configs", sa.Column("enricher_model", sa.String(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("normalizer_model", sa.String(), nullable=True))
    op.add_column("workspace_llm_configs", sa.Column("validator_model", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "validator_model")
    op.drop_column("workspace_llm_configs", "normalizer_model")
    op.drop_column("workspace_llm_configs", "enricher_model")
