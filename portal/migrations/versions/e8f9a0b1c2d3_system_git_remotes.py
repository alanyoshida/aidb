"""Vínculo de um sistema com um repositório git remoto (change add-system-git-remote, design D2).

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-11-20 13:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'e8f9a0b1c2d3'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'system_git_remotes',
        sa.Column('system_id', sa.String(32), sa.ForeignKey('systems.id'), primary_key=True),
        sa.Column('url', sa.String(500), nullable=False, server_default=''),
        sa.Column('working_branch', sa.String(200), nullable=False, server_default='homolog'),
        sa.Column('target_branch', sa.String(200), nullable=False, server_default='main'),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('private_key_encrypted', sa.Text(), nullable=False),
        sa.Column('host_key', sa.Text(), nullable=True),
        sa.Column('api_url', sa.String(500), nullable=False, server_default=''),
        sa.Column('api_token_encrypted', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('state', sa.String(20), nullable=False, server_default='synced'),
        sa.Column('state_detail', sa.Text(), nullable=False, server_default=''),
        sa.Column('last_pushed_sha', sa.String(64), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('conflict_files', sa.JSON(), nullable=True),
        sa.Column('merge_in_progress', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('unsaved_blocked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('last_mr_url', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('system_git_remotes')
