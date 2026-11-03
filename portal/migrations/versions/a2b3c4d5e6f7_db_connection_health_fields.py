"""Adicionar campos status e status_checked_at em db_connections.

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-11-03 11:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'a2b3c4d5e6f7'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('db_connections', sa.Column('status', sa.String(20), nullable=False, server_default='unknown'))
    op.add_column('db_connections', sa.Column('status_checked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('db_connections', 'status_checked_at')
    op.drop_column('db_connections', 'status')
