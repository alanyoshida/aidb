"""Ampliar password_encrypted de VARCHAR(500) para TEXT em db_connections.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-03 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'db_connections',
        'password_encrypted',
        existing_type=sa.String(500),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'db_connections',
        'password_encrypted',
        existing_type=sa.Text(),
        type_=sa.String(500),
        existing_nullable=False,
    )
