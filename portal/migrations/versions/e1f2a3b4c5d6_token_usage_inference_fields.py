"""Adiciona custo e id externo (idempotência) em token_usage (etapa 3, ADR 0020).

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-11-05 18:45:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'e1f2a3b4c5d6'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('token_usage', sa.Column('cost', sa.Float(), nullable=False, server_default='0'))
    op.add_column('token_usage', sa.Column('external_id', sa.String(length=120), nullable=True))
    op.create_index('ix_token_usage_external_id', 'token_usage', ['external_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_token_usage_external_id', table_name='token_usage')
    op.drop_column('token_usage', 'external_id')
    op.drop_column('token_usage', 'cost')
