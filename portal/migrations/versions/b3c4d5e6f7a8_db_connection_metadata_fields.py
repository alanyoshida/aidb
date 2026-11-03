"""Adicionar campos description e access_mode em db_connections.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-11-03 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('db_connections', sa.Column('description', sa.String(500), nullable=True))
    op.add_column('db_connections', sa.Column('access_mode', sa.String(20), nullable=False, server_default='read_write'))


def downgrade() -> None:
    op.drop_column('db_connections', 'access_mode')
    op.drop_column('db_connections', 'description')
