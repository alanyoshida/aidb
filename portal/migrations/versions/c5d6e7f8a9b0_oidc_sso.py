"""SSO por OIDC, break-glass e trava do modo de autenticação (change add-oidc-sso).

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-16 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('users', 'password_hash', existing_type=sa.String(255), nullable=True)
    op.add_column('users', sa.Column('idp_subject', sa.String(255), nullable=True))
    op.create_unique_constraint('uq_users_idp_subject', 'users', ['idp_subject'])
    op.add_column('users', sa.Column('break_glass', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('sessions', sa.Column('auth_method', sa.String(20), nullable=False, server_default='local'))
    op.add_column('sessions', sa.Column('user_type', sa.String(20), nullable=True))
    op.add_column('sessions', sa.Column('groups', sa.JSON(), nullable=True))
    op.add_column('sessions', sa.Column('refresh_token_enc', sa.Text(), nullable=True))
    op.add_column('sessions', sa.Column('id_token_enc', sa.Text(), nullable=True))
    op.add_column('sessions', sa.Column('revalidate_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'portal_instance',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('auth_mode', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'observed_idp_groups',
        sa.Column('name', sa.String(255), primary_key=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Instalação existente (já tem usuários) era, por definição, local: grava a trava
    # agora para que subir com APPAIFORGE_AUTH_MODE=oidc sobre ela seja recusado.
    op.execute(
        "INSERT INTO portal_instance (id, auth_mode, created_at) "
        "SELECT 1, 'local', now() WHERE EXISTS (SELECT 1 FROM users)"
    )


def downgrade() -> None:
    op.drop_table('observed_idp_groups')
    op.drop_table('portal_instance')
    for col in ('revalidate_at', 'id_token_enc', 'refresh_token_enc', 'groups', 'user_type', 'auth_method'):
        op.drop_column('sessions', col)
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'break_glass')
    op.drop_constraint('uq_users_idp_subject', 'users', type_='unique')
    op.drop_column('users', 'idp_subject')
    # Usuários-sombra (sem senha) não têm como voltar a um schema que exige senha.
    op.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE password_hash IS NULL)")
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column('users', 'password_hash', existing_type=sa.String(255), nullable=False)
