"""rename organizations to workspaces

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-06-03 00:00:00.000000

Renames all org* tables/columns to workspace* terminology.
SQLite requires batch_alter_table for column renames and FK recreation.
Existing rows are preserved; cache_namespace values are unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
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
    # 1. Rename organizations → workspaces
    op.rename_table("organizations", "workspaces")

    # 2. departments: rename org_id → workspace_id, update FK, rename constraint
    with op.batch_alter_table("departments", recreate="always") as batch_op:
        batch_op.alter_column("org_id", new_column_name="workspace_id")
        # Unique constraint was uq_dept_org_slug; rename to uq_dept_workspace_slug
        # (SQLite will recreate the table so the new constraint name is set below)
        batch_op.drop_constraint("uq_dept_org_slug", type_="unique")
        batch_op.create_unique_constraint("uq_dept_workspace_slug", ["workspace_id", "slug"])

    # 3. api_keys: rename org_id → workspace_id, update FK
    with op.batch_alter_table("api_keys", recreate="always") as batch_op:
        batch_op.alter_column("org_id", new_column_name="workspace_id")

    # 4. org_llm_config → workspace_llm_configs: rename table, rename PK column
    op.rename_table("org_llm_config", "workspace_llm_configs")
    with op.batch_alter_table("workspace_llm_configs", recreate="always") as batch_op:
        batch_op.alter_column("org_id", new_column_name="workspace_id")

    # 5. org_provider_credentials → workspace_provider_credentials
    op.rename_table("org_provider_credentials", "workspace_provider_credentials")
    with op.batch_alter_table("workspace_provider_credentials", recreate="always") as batch_op:
        batch_op.alter_column("org_id", new_column_name="workspace_id")
        batch_op.drop_constraint("uq_org_provider_credentials_org_provider", type_="unique")
        batch_op.create_unique_constraint(
            "uq_workspace_provider_credentials_workspace_provider",
            ["workspace_id", "provider"],
        )

    # 6. user_org_memberships → user_workspace_memberships
    op.rename_table("user_org_memberships", "user_workspace_memberships")
    with op.batch_alter_table("user_workspace_memberships", recreate="always") as batch_op:
        batch_op.alter_column("org_id", new_column_name="workspace_id")
        batch_op.drop_constraint("uq_user_org", type_="unique")
        batch_op.create_unique_constraint("uq_user_workspace", ["user_id", "workspace_id"])


def downgrade() -> None:
    # Reverse: workspace_* → org_*
    op.rename_table("user_workspace_memberships", "user_org_memberships")
    with op.batch_alter_table("user_org_memberships", recreate="always") as batch_op:
        batch_op.alter_column("workspace_id", new_column_name="org_id")
        batch_op.drop_constraint("uq_user_workspace", type_="unique")
        batch_op.create_unique_constraint("uq_user_org", ["user_id", "org_id"])

    op.rename_table("workspace_provider_credentials", "org_provider_credentials")
    with op.batch_alter_table("org_provider_credentials", recreate="always") as batch_op:
        batch_op.alter_column("workspace_id", new_column_name="org_id")
        batch_op.drop_constraint("uq_workspace_provider_credentials_workspace_provider", type_="unique")
        batch_op.create_unique_constraint(
            "uq_org_provider_credentials_org_provider", ["org_id", "provider"]
        )

    op.rename_table("workspace_llm_configs", "org_llm_config")
    with op.batch_alter_table("org_llm_config", recreate="always") as batch_op:
        batch_op.alter_column("workspace_id", new_column_name="org_id")

    with op.batch_alter_table("api_keys", recreate="always") as batch_op:
        batch_op.alter_column("workspace_id", new_column_name="org_id")

    with op.batch_alter_table("departments", recreate="always") as batch_op:
        batch_op.alter_column("workspace_id", new_column_name="org_id")
        batch_op.drop_constraint("uq_dept_workspace_slug", type_="unique")
        batch_op.create_unique_constraint("uq_dept_org_slug", ["org_id", "slug"])

    op.rename_table("workspaces", "organizations")
