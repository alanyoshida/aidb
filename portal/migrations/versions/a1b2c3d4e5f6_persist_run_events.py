"""Persistir eventos de execução do agente (correção do chat).

Revision ID: a1b2c3d4e5f6
Revises: 343fcb4c0345
Create Date: 2026-11-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '343fcb4c0345'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'run_events',
        sa.Column('id', sa.String(32), nullable=False),
        sa.Column('run_id', sa.String(32), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('text', sa.Text(), nullable=False, server_default=''),
        sa.Column('meta', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_run_events_run_id', 'run_id'),
    )


def downgrade() -> None:
    op.drop_table('run_events')
