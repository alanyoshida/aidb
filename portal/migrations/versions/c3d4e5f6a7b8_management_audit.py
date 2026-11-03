"""Trilha de auditoria das ações de gestão do portal.

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-11-02 20:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c3d4e5f6a7b8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'management_audit',
        sa.Column('id', sa.String(32), nullable=False),
        sa.Column('actor_id', sa.String(32), nullable=True),
        sa.Column('action', sa.String(60), nullable=False),
        sa.Column('resource_type', sa.String(40), nullable=False),
        sa.Column('resource_id', sa.String(64), nullable=True),
        sa.Column('system_id', sa.String(32), nullable=True),
        sa.Column('details', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['system_id'], ['systems.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_management_audit_actor_id', 'actor_id'),
        sa.Index('ix_management_audit_action', 'action'),
        sa.Index('ix_management_audit_resource_type', 'resource_type'),
        sa.Index('ix_management_audit_system_id', 'system_id'),
        sa.Index('ix_management_audit_created_at', 'created_at'),
    )


def downgrade() -> None:
    op.drop_table('management_audit')