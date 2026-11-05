"""Adiciona modo de execução do container por sistema (ADR 0018).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-11-04 21:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None

execution_mode = sa.Enum('legacy', 'reduced', name='execution_mode')


def upgrade() -> None:
    execution_mode.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'systems',
        # server_default='legacy' preserva o comportamento dos sistemas
        # existentes (root, sem identidade reduzida); só sistemas criados a
        # partir desta mudança nascem em 'reduced' (default do modelo).
        sa.Column('execution_mode', execution_mode, nullable=False, server_default='legacy'),
    )


def downgrade() -> None:
    op.drop_column('systems', 'execution_mode')
    execution_mode.drop(op.get_bind(), checkfirst=True)
