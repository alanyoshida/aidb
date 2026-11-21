"""Identidade da instalação (change add-production-portal-install, design D1).

`portal_instance.installation_id`, anulável: o boot preenche a linha que não tiver valor.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-11-21 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'a0b1c2d3e4f5'
down_revision = 'f9a0b1c2d3e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('portal_instance', sa.Column('installation_id', sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column('portal_instance', 'installation_id')
