"""add org provider credentials

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-28 00:00:00.000000

Downgrade destroys all stored encrypted credentials. Operators must re-enter every org's API keys after a re-upgrade.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROVIDERS = (
    "google",
    "openai",
    "anthropic",
    "mistral",
    "cohere",
    "together",
    "groq",
    "fireworks",
)


def upgrade() -> None:
    op.create_table(
        "org_provider_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "provider", name="uq_org_provider_credentials_org_provider"),
        sa.CheckConstraint(
            "provider IN ('google', 'openai', 'anthropic', 'mistral', 'cohere', 'together', 'groq', 'fireworks')",
            name="ck_org_provider_credentials_provider",
        ),
    )


def downgrade() -> None:
    op.drop_table("org_provider_credentials")
