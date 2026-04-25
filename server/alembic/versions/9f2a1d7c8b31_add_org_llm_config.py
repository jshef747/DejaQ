"""add org llm config

Revision ID: 9f2a1d7c8b31
Revises: 4768d0a3e5b4
Create Date: 2026-04-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9f2a1d7c8b31"
down_revision = "4768d0a3e5b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_llm_config",
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("external_model", sa.String(), nullable=True),
        sa.Column("local_model", sa.String(), nullable=True),
        sa.Column("routing_threshold", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )


def downgrade() -> None:
    op.drop_table("org_llm_config")
