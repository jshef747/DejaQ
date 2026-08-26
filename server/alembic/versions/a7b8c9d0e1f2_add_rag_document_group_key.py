"""add rag_documents.group_key

Revision ID: a7b8c9d0e1f2
Revises: d4e5f6a7b8c9
Create Date: 2026-08-26 00:00:00.000000

A GitHub repository import writes one catalog row PER FILE (provenance: an
answer grounded in the repo has to say which file it came from, and the
existing per-document sha identity then does per-file replace for free).
Without a grouping handle that is hundreds of loose rows in the dashboard
list, and a re-import has no way to find the rows belonging to the previous
version of the same repo.

Nullable on purpose: every existing source (paste, upload, URL) is a single
document and stays ungrouped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rag_documents", sa.Column("group_key", sa.String(), nullable=True))
    op.create_index(
        "ix_rag_documents_group_key", "rag_documents", ["workspace_id", "group_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_rag_documents_group_key", table_name="rag_documents")
    op.drop_column("rag_documents", "group_key")
