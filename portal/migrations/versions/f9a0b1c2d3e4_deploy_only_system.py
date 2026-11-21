"""Sistema só implantação (change add-deploy-only-system, design D1/D3).

`systems.kind` (`agent` | `deploy_only`, existentes ficam `agent`), configuração de implantação por
sistema e histórico de implantações.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-11-20 18:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'f9a0b1c2d3e4'
down_revision = 'e8f9a0b1c2d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('systems', sa.Column('kind', sa.String(20), nullable=False, server_default='agent'))
    op.create_table(
        'deploy_settings',
        sa.Column('system_id', sa.String(32), sa.ForeignKey('systems.id'), primary_key=True),
        sa.Column('tag_pattern', sa.String(100), nullable=False, server_default='v*'),
        sa.Column('mode', sa.String(20), nullable=False, server_default='manual'),
        sa.Column('detection', sa.String(20), nullable=False, server_default='polling'),
        sa.Column('webhook_secret_encrypted', sa.Text(), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'deployments',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('system_id', sa.String(32), sa.ForeignKey('systems.id'), nullable=False, index=True),
        sa.Column('tag', sa.String(200), nullable=False),
        sa.Column('commit_sha', sa.String(64), nullable=False, server_default=''),
        sa.Column('trigger', sa.String(20), nullable=False),
        sa.Column('actor_id', sa.String(32), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False, server_default=''),
        sa.Column('previous_sha', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('deployments')
    op.drop_table('deploy_settings')
    op.drop_column('systems', 'kind')
