"""Origem de cada checkpoint (change isolate-workspace-repository, design D5).

`run` (execução do agente), `manual` (botão na aba Checkpoints), `restore` (restauração de um
checkpoint anterior, que passa a ser um commit novo em vez de reescrever o histórico). Texto
livre, para changes seguintes acrescentarem valores (ex.: `remote`) sem migração de tipo.
Registros existentes ficam como `run`.

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-11-20 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'd7e8f9a0b1c2'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('checkpoints', sa.Column('origin', sa.String(20), nullable=False, server_default='run'))


def downgrade() -> None:
    op.drop_column('checkpoints', 'origin')
