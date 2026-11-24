"""Modelo do catálogo de conexões (change add-db-manager-role, task 1.2, design D3)."""

import pytest
from sqlalchemy.exc import IntegrityError

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import DbConnection, DbConnectionGrant, SystemConnectionNotice, UserType
from appaiforge.services.systems import create_system


@pytest.fixture()
def two_systems(clean_db):
    editor = auth.create_user("ed@catalog.local", "pw", UserType.editor.value)
    return create_system(editor, "A", "sys-a"), create_system(editor, "B", "sys-b")


def _connection(name="vendas") -> str:
    with session_scope() as s:
        conn = DbConnection(
            name=name, kind="postgres", host="db", port=5432, database="vendas",
            username="app", password_encrypted="x",
        )
        s.add(conn)
        s.flush()
        return conn.id


def _grant(conn_id, system_id, **kw) -> str:
    with session_scope() as s:
        grant = DbConnectionGrant(connection_id=conn_id, system_id=system_id, **kw)
        s.add(grant)
        s.flush()
        return grant.id


def test_conexao_com_duas_autorizacoes_e_um_aviso(two_systems):
    a, b = two_systems
    conn_id = _connection()
    _grant(conn_id, a.id, active=True, alias="vendas", alias_key="VENDAS", mode="read_only", max_mode="read_write")
    _grant(conn_id, b.id)
    with session_scope() as s:
        s.add(SystemConnectionNotice(system_id=a.id, kind="revoked", connection_name="vendas", alias="vendas"))
    with session_scope() as s:
        grants = s.query(DbConnectionGrant).filter_by(connection_id=conn_id).all()
        assert len(grants) == 2
        inactive = next(g for g in grants if g.system_id == b.id)
        assert inactive.active is False
        assert inactive.max_mode == "read_write"
        assert s.query(SystemConnectionNotice).count() == 1


def test_nome_unico_no_catalogo(two_systems):
    _connection("vendas")
    with pytest.raises(IntegrityError):
        _connection("vendas")


def test_autorizacao_duplicada_recusada_pelo_banco(two_systems):
    a, _ = two_systems
    conn_id = _connection()
    _grant(conn_id, a.id)
    with pytest.raises(IntegrityError):
        _grant(conn_id, a.id)


def test_alias_repetido_entre_ativas_recusado_pelo_banco(two_systems):
    a, _ = two_systems
    c1, c2 = _connection("vendas"), _connection("estoque")
    _grant(c1, a.id, active=True, alias="main", alias_key="MAIN")
    with pytest.raises(IntegrityError):
        _grant(c2, a.id, active=True, alias="main", alias_key="MAIN")


def test_alias_repetido_permitido_quando_uma_esta_inativa(two_systems):
    a, _ = two_systems
    c1, c2 = _connection("vendas"), _connection("estoque")
    _grant(c1, a.id, active=True, alias="main", alias_key="MAIN")
    _grant(c2, a.id, active=False, alias="main", alias_key="MAIN")


def test_mesmo_alias_em_sistemas_diferentes(two_systems):
    a, b = two_systems
    conn_id = _connection()
    _grant(conn_id, a.id, active=True, alias="main", alias_key="MAIN")
    _grant(conn_id, b.id, active=True, alias="main", alias_key="MAIN")
