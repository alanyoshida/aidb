"""Adiciona preferência de tema por usuário.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-11-03 14:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'd1e2f3a4b5c6'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('theme', sa.String(32), nullable=False, server_default='light-indigo'),
    )


def downgrade() -> None:
    op.drop_column('users', 'theme')
