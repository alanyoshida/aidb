"""Adiciona versão do token opaco de inferência por sistema (etapa 3, ADR 0020).

Revision ID: b8c9d0e1f2a3
Revises: f3a4b5c6d7e8
Create Date: 2026-11-05 18:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'b8c9d0e1f2a3'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'systems',
        # default 0 preserva os sistemas existentes; revogar = incrementar.
        sa.Column('inference_token_version', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('systems', 'inference_token_version')
