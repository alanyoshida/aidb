"""Unitários do serviço de conexões: cifra em repouso e não-vazamento (task 3.3).

O cadastro exige conexão real, então os testes apontam para o Postgres da
sessão (fixture live_pg).
"""

import logging

import pytest

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import UserType
from appaiforge.services import connections
from appaiforge.services.systems import create_system

SECRET = "sup3r-senha-do-banco"


@pytest.fixture()
def system(clean_db):
    editor = auth.create_user("ed@conn.local", "pw", UserType.editor.value)
    return create_system(editor, "ERP", "erp")


@pytest.fixture()
def target(live_pg):
    return live_pg


def _register(system, target):
    return connections.register_connection(
        system, "principal", target["host"], target["port"], target["database"], target["username"], target["password"]
    )


def test_senha_cifrada_em_repouso(system, target):
    conn = _register(system, target)
    from sqlalchemy import text

    with session_scope() as s:
        raw = s.execute(
            text("SELECT password_encrypted FROM db_connections WHERE id = :id"), {"id": conn.id}
        ).scalar_one()
    # a coluna guarda cifra, não texto puro; a cifra devolve o valor original
    assert target["password"] not in raw
    assert connections.decrypt_secret(raw) == target["password"]


def test_listagem_nao_expos_senha(system, target):
    _register(system, target)
    listing = connections.list_connections(system.id)
    assert listing and "password" not in listing[0]
    assert SECRET not in str(listing)


def test_logs_nao_contem_senha(system, target, caplog):
    with caplog.at_level(logging.DEBUG, logger="appaiforge.services.connections"):
        _register(system, target)
        conn2 = connections.register_connection(
            system, "secundaria", target["host"], target["port"], target["database"], target["username"], target["password"]
        )
        connections.remove_connection(system, conn2.id)
    all_logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert SECRET not in all_logs


def test_nome_duplicado_no_mesmo_sistema(system, target):
    _register(system, target)
    with pytest.raises(connections.NameTaken):
        _register(system, target)


def test_mesmo_nome_em_sistemas_diferentes_e_permitido(clean_db, target):
    editor = auth.create_user("ed2@conn.local", "pw", UserType.editor.value)
    sys1 = create_system(editor, "A", "sys-a")
    sys2 = create_system(editor, "B", "sys-b")
    _register(sys1, target)
    conn2 = _register(sys2, target)
    assert conn2.system_id == sys2.id


def test_remocao_cessa_registro(system, target):
    conn = _register(system, target)
    connections.remove_connection(system, conn.id)
    assert connections.list_connections(system.id) == []
