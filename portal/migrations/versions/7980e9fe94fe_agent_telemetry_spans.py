"""Tabela de spans de telemetria pro Debug log (change agent-telemetry-backend-agnostic).

Revision ID: 7980e9fe94fe
Revises: b2c3d4e5f6a8
Create Date: 2026-11-09 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '7980e9fe94fe'
down_revision = 'b2c3d4e5f6a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'agent_telemetry_spans',
        sa.Column('id', sa.String(32), nullable=False),
        sa.Column('run_id', sa.String(32), nullable=False),
        sa.Column('span_id', sa.String(32), nullable=False),
        sa.Column('parent_span_id', sa.String(32), nullable=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attributes', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_agent_telemetry_spans_run_id', 'run_id'),
        sa.Index('ix_agent_telemetry_spans_end_time', 'end_time'),
    )


def downgrade() -> None:
    op.drop_table('agent_telemetry_spans')
