"""Adiciona title e context_reset a chat_sessions para gerenciamento de sessões.

Revision ID: c9d0e1f2a3b4
Revises: b3c4d5e6f7a8
Create Date: 2026-11-03 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'c9d0e1f2a3b4'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chat_sessions', sa.Column('title', sa.String(100), nullable=True))
    op.add_column('chat_sessions', sa.Column('context_reset', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('chat_sessions', 'context_reset')
    op.drop_column('chat_sessions', 'title')
