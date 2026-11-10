"""Adiciona perfil de runtime do agente por sistema (change generalize-agent-runtime-plumbing,
spec agent-runtime - "Perfil de runtime por sistema").

Revision ID: b4c5d6e7f8a9
Revises: 7980e9fe94fe
Create Date: 2026-11-09 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'b4c5d6e7f8a9'
down_revision = '7980e9fe94fe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # String livre, não Enum: o conjunto de perfis é extensível (spec
    # agent-runtime - "Conjunto de perfis extensível"), uma constraint de
    # banco fixa contrariaria isso. server_default='opencode' preserva o
    # perfil de todo sistema existente (o único que existia antes desta
    # mudança), mesmo padrão usado em execution_mode.
    op.add_column(
        'systems',
        sa.Column('agent_profile', sa.String(60), nullable=False, server_default='opencode'),
    )


def downgrade() -> None:
    op.drop_column('systems', 'agent_profile')
