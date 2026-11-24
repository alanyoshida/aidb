"""Catálogo de conexões e autorizações por sistema (change add-db-manager-role, D3).

- `users.db_manager` e `sessions.db_manager` (capacidade de DB Manager, D1/D2);
- `db_connection_grants` (autorização, teto, ativação e alias) e `system_connection_notices`;
- cada conexão existente vira item do catálogo autorizado e ativo no sistema de origem, com o
  nome anterior como alias e o `access_mode` anterior como teto e modo vigente;
- a conexão é renomeada no catálogo para `<nome> (<slug>)`, para o nome ser único;
- `db_connections` perde `system_id` e `access_mode`.

Duas conexões do mesmo sistema cujos nomes geravam a mesma variável de ambiente (ex.: `a-b`
e `a_b`) já se sobrescreviam antes; a mais antiga continua ativa, as demais ficam inativas e
o dono recebe um aviso.

Revision ID: b6c7d8e9f0a1
Revises: a0b1c2d3e4f5
Create Date: 2026-11-24 12:00:00.000000

"""
import re
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = 'b6c7d8e9f0a1'
down_revision = 'a0b1c2d3e4f5'
branch_labels = None
depends_on = None

NAME_MAX = 120


def _env_key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", name.upper())


def _catalog_name(name: str, slug: str, taken: set[str], conn_id: str) -> str:
    suffix = f" ({slug})"
    candidate = name[: NAME_MAX - len(suffix)] + suffix
    if candidate in taken:
        suffix = f" ({slug}) {conn_id[:6]}"
        candidate = name[: NAME_MAX - len(suffix)] + suffix
    return candidate


def upgrade() -> None:
    op.add_column('users', sa.Column('db_manager', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('sessions', sa.Column('db_manager', sa.Boolean(), nullable=True))
    op.create_table(
        'db_connection_grants',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('connection_id', sa.String(32), sa.ForeignKey('db_connections.id'), nullable=False),
        sa.Column('system_id', sa.String(32), sa.ForeignKey('systems.id'), nullable=False),
        sa.Column('max_mode', sa.String(20), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('alias', sa.String(120), nullable=True),
        sa.Column('alias_key', sa.String(120), nullable=True),
        sa.Column('mode', sa.String(20), nullable=False),
        sa.Column('schema_admin_since', sa.DateTime(timezone=True), nullable=True),
        sa.Column('granted_by_email', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('connection_id', 'system_id', name='uq_grant_connection_system'),
    )
    op.create_index('ix_db_connection_grants_connection_id', 'db_connection_grants', ['connection_id'])
    op.create_index('ix_db_connection_grants_system_id', 'db_connection_grants', ['system_id'])
    op.create_table(
        'system_connection_notices',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('system_id', sa.String(32), sa.ForeignKey('systems.id'), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('connection_name', sa.String(120), nullable=False),
        sa.Column('alias', sa.String(120), nullable=True),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('actor_email', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_system_connection_notices_system_id', 'system_connection_notices', ['system_id'])

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT c.id, c.system_id, c.name, c.access_mode, c.created_at, s.slug "
        "FROM db_connections c JOIN systems s ON s.id = c.system_id "
        "ORDER BY c.system_id, c.created_at, c.id"
    )).all()
    now = datetime.now(timezone.utc)
    taken: set[str] = set()
    active_keys: set[tuple[str, str]] = set()
    for conn_id, system_id, name, access_mode, created_at, slug in rows:
        mode = access_mode if access_mode in ('read_only', 'read_write') else 'read_write'
        key = _env_key(name)
        active = (system_id, key) not in active_keys
        if active:
            active_keys.add((system_id, key))
        bind.execute(
            sa.text(
                "INSERT INTO db_connection_grants (id, connection_id, system_id, max_mode, active, "
                "alias, alias_key, mode, created_at) VALUES (:id, :cid, :sid, :mode, :active, "
                ":alias, :key, :mode, :created)"
            ),
            {"id": uuid.uuid4().hex, "cid": conn_id, "sid": system_id, "mode": mode, "active": active,
             "alias": name, "key": key, "created": created_at or now},
        )
        if not active:
            bind.execute(
                sa.text(
                    "INSERT INTO system_connection_notices (id, system_id, kind, connection_name, alias, "
                    "detail, created_at) VALUES (:id, :sid, 'migration_conflict', :name, :alias, :detail, :now)"
                ),
                {"id": uuid.uuid4().hex, "sid": system_id, "name": name, "alias": name, "now": now,
                 "detail": "a conexão gerava a mesma variável de ambiente que outra conexão do sistema "
                           "e ficou inativa; ative-a com outro alias se ainda for usada"},
            )
        catalog_name = _catalog_name(name, slug, taken, conn_id)
        taken.add(catalog_name)
        bind.execute(sa.text("UPDATE db_connections SET name = :n WHERE id = :id"), {"n": catalog_name, "id": conn_id})

    op.create_index(
        'uq_grant_active_alias', 'db_connection_grants', ['system_id', 'alias_key'], unique=True,
        postgresql_where=sa.text('active'),
    )
    op.drop_constraint('uq_connection_per_system', 'db_connections', type_='unique')
    op.drop_index('ix_db_connections_system_id', table_name='db_connections')
    op.drop_column('db_connections', 'system_id')
    op.drop_column('db_connections', 'access_mode')
    op.create_unique_constraint('db_connections_name_key', 'db_connections', ['name'])


def downgrade() -> None:
    bind = op.get_bind()
    counts = bind.execute(sa.text(
        "SELECT c.name, count(g.id) FROM db_connections c "
        "LEFT JOIN db_connection_grants g ON g.connection_id = c.id GROUP BY c.id, c.name"
    )).all()
    bad = sorted(name for name, n in counts if n != 1)
    if bad:
        raise RuntimeError(
            "não é possível voltar ao modelo de conexão por sistema: estas conexões não têm "
            "exatamente uma autorização (restaure o backup do banco do portal): " + ", ".join(bad)
        )
    op.add_column('db_connections', sa.Column('system_id', sa.String(32), nullable=True))
    op.add_column('db_connections', sa.Column('access_mode', sa.String(20), nullable=False, server_default='read_write'))
    op.drop_constraint('db_connections_name_key', 'db_connections', type_='unique')
    bind.execute(sa.text(
        "UPDATE db_connections c SET system_id = g.system_id, "
        "access_mode = CASE WHEN g.mode = 'read_only' THEN 'read_only' ELSE 'read_write' END, "
        "name = COALESCE(g.alias, c.name) "
        "FROM db_connection_grants g WHERE g.connection_id = c.id"
    ))
    op.alter_column('db_connections', 'system_id', nullable=False)
    op.create_foreign_key('db_connections_system_id_fkey', 'db_connections', 'systems', ['system_id'], ['id'])
    op.create_index('ix_db_connections_system_id', 'db_connections', ['system_id'])
    op.create_unique_constraint('uq_connection_per_system', 'db_connections', ['system_id', 'name'])
    op.drop_index('uq_grant_active_alias', table_name='db_connection_grants')
    op.drop_table('system_connection_notices')
    op.drop_table('db_connection_grants')
    op.drop_column('sessions', 'db_manager')
    op.drop_column('users', 'db_manager')
