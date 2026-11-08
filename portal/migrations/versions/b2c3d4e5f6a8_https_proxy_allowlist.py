"""https proxy allowlist

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-11-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a8'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('systems', sa.Column('internet_enabled', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('systems', sa.Column('restricted_network', sa.Boolean(), server_default='false', nullable=False))

    op.create_table('allowed_domains',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('system_id', sa.String(length=32), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=False),
    sa.Column('author_id', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['system_id'], ['systems.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('system_id', 'domain', name='uq_allowed_domain_per_system')
    )
    op.create_index(op.f('ix_allowed_domains_system_id'), 'allowed_domains', ['system_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_allowed_domains_system_id'), table_name='allowed_domains')
    op.drop_table('allowed_domains')
    op.drop_column('systems', 'restricted_network')
    op.drop_column('systems', 'internet_enabled')
