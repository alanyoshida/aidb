"""Adiciona o modo de execução 'sandboxed' (etapa 2 do confinamento, capability agent-sandbox).

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-05 00:00:00.000000

"""
from alembic import op

revision = 'f3a4b5c6d7e8'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sistemas existentes (legacy/reduced) não mudam de modo: só sistemas
    # novos passam a poder nascer 'sandboxed', decidido em
    # provisioning.decide_execution_mode() na criação do sistema.
    op.execute("ALTER TYPE execution_mode ADD VALUE IF NOT EXISTS 'sandboxed'")


def downgrade() -> None:
    # Postgres não suporta remover um valor de enum; reverter exige recriar o
    # tipo, o que falharia se alguma linha já estiver em 'sandboxed'.
    raise NotImplementedError(
        "downgrade de execution_mode=sandboxed não suportado: "
        "Postgres não remove valores de enum; migre linhas 'sandboxed' "
        "para 'reduced' manualmente antes de tentar reverter"
    )
