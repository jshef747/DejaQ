"""drop the orphan users and user_workspace_memberships tables

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-03 00:00:00.000000

`users` and `user_workspace_memberships` are created by the migration chain
(a1b2c3d4e5f6, renamed in d1e2f3a4b5c6) but their SQLAlchemy models were
deleted and no app code references either table - `alembic upgrade head` and
`Base.metadata.create_all` disagree only on these two tables (and the
departments constraint b7c8d9e0f1a2 restores). They are always-empty dead
schema; drop them so the migrated schema matches the ORM.
"""
from alembic import op
import sqlalchemy as sa


revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("user_workspace_memberships")
    op.drop_index("ix_users_supabase_user_id", "users")
    op.drop_table("users")


def downgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("supabase_user_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_users_supabase_user_id", "users", ["supabase_user_id"], unique=True)

    op.create_table(
        "user_workspace_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "workspace_id", name="uq_user_workspace"),
    )
    op.create_index("ix_user_org_memberships_user_id", "user_workspace_memberships", ["user_id"])
    op.create_index("ix_user_org_memberships_org_id", "user_workspace_memberships", ["workspace_id"])
