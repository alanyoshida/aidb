"""Histórico guarda o e-mail do autor e a FK de usuário fica nulável.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-02 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # colunas de e-mail do autor (denormalizado), com backfill a partir de users
    op.add_column('agent_runs', sa.Column('user_email', sa.String(255), nullable=False, server_default=''))
    op.add_column('token_usage', sa.Column('user_email', sa.String(255), nullable=False, server_default=''))
    op.add_column('checkpoints', sa.Column('author_email', sa.String(255), nullable=False, server_default=''))
    op.add_column('guidelines', sa.Column('updated_by_email', sa.String(255), nullable=False, server_default=''))
    op.add_column('gate_decisions', sa.Column('author_email', sa.String(255), nullable=False, server_default=''))
    op.add_column('management_audit', sa.Column('actor_email', sa.String(255), nullable=False, server_default=''))

    op.execute("UPDATE agent_runs a SET user_email = u.email FROM users u WHERE u.id = a.user_id")
    op.execute("UPDATE token_usage t SET user_email = u.email FROM users u WHERE u.id = t.user_id")
    op.execute("UPDATE checkpoints c SET author_email = u.email FROM users u WHERE u.id = c.author_id")
    op.execute("UPDATE guidelines g SET updated_by_email = u.email FROM users u WHERE u.id = g.updated_by_id")
    op.execute("UPDATE gate_decisions d SET author_email = u.email FROM users u WHERE u.id = d.author_id")
    op.execute("UPDATE management_audit m SET actor_email = u.email FROM users u WHERE u.id = m.actor_id")

    # a referência ao usuário passa a ser desacoplável (histórico sobrevive à exclusão)
    op.alter_column('agent_runs', 'user_id', existing_type=sa.String(32), nullable=True)
    op.alter_column('token_usage', 'user_id', existing_type=sa.String(32), nullable=True)
    op.alter_column('checkpoints', 'author_id', existing_type=sa.String(32), nullable=True)
    op.alter_column('guidelines', 'updated_by_id', existing_type=sa.String(32), nullable=True)


def downgrade() -> None:
    op.alter_column('guidelines', 'updated_by_id', existing_type=sa.String(32), nullable=False)
    op.alter_column('checkpoints', 'author_id', existing_type=sa.String(32), nullable=False)
    op.alter_column('token_usage', 'user_id', existing_type=sa.String(32), nullable=False)
    op.alter_column('agent_runs', 'user_id', existing_type=sa.String(32), nullable=False)

    op.drop_column('management_audit', 'actor_email')
    op.drop_column('gate_decisions', 'author_email')
    op.drop_column('guidelines', 'updated_by_email')
    op.drop_column('checkpoints', 'author_email')
    op.drop_column('token_usage', 'user_email')
    op.drop_column('agent_runs', 'user_email')