"""add_rag_document_ingest_status

Revision ID: b1c2d3e4f5a6
Revises: a6b7c8d9e0f1
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('rag_documents', sa.Column('status', sa.String(), nullable=False, server_default='ready'))
    op.add_column('rag_documents', sa.Column('progress_current', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('rag_documents', sa.Column('progress_total', sa.Integer(), nullable=True))
    op.add_column('rag_documents', sa.Column('error_message', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('rag_documents', 'error_message')
    op.drop_column('rag_documents', 'progress_total')
    op.drop_column('rag_documents', 'progress_current')
    op.drop_column('rag_documents', 'status')
