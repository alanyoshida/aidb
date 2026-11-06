"""Adiciona revogação seletiva da inferência por sessão (etapa 3, ADR 0020).

Revision ID: d9e0f1a2b3c4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-05 18:30:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'd9e0f1a2b3c4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'chat_sessions',
        sa.Column('inference_revoked', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('chat_sessions', 'inference_revoked')
