"""run awaiting approval

Revision ID: 343fcb4c0345
Revises: 6154658171b0
Create Date: 2026-11-02 09:50:55.929120

"""
from alembic import op


revision = '343fcb4c0345'
down_revision = '6154658171b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic não detecta mudanças em enum nativo — valor novo do run_status
    op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'awaiting_approval'")


def downgrade() -> None:
    # remover valor de enum não é suportado pelo Postgres; downgrade é no-op
    pass
