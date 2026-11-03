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


def _stored_password(conn_id):
    from sqlalchemy import text

    with session_scope() as s:
        return s.execute(
            text("SELECT password_encrypted FROM db_connections WHERE id = :id"), {"id": conn_id}
        ).scalar_one()


def test_edicao_senha_vazia_mantem_a_atual(system, target):
    conn = _register(system, target)
    connections.update_connection(
        system, conn.id, "principal", target["host"], target["port"], target["database"], target["username"],
        password=None,
    )
    assert connections.decrypt_secret(_stored_password(conn.id)) == target["password"]


def test_edicao_com_senha_troca_a_cifra(system, target):
    conn = _register(system, target)
    before = _stored_password(conn.id)
    connections.update_connection(
        system, conn.id, "principal", target["host"], target["port"], target["database"], target["username"],
        password=target["password"],
    )
    after = _stored_password(conn.id)
    assert after != before  # re-cifra mesmo com o mesmo texto
    assert connections.decrypt_secret(after) == target["password"]


def test_edicao_com_senha_errada_recusa(system, target):
    conn = _register(system, target)
    with pytest.raises(connections.ConnectionFailed):
        connections.update_connection(
            system, conn.id, "principal", target["host"], target["port"], target["database"], target["username"],
            password="senha-errada",
        )


def test_edicao_de_metadados_reflete_na_lista(system, target):
    conn = _register(system, target)
    connections.update_connection(
        system, conn.id, "renomeada", target["host"], target["port"], target["database"], target["username"],
        password=None,
    )
    listing = connections.list_connections(system.id)
    assert listing[0]["name"] == "renomeada"


def test_listagem_inclui_status_e_sem_senha(system, target):
    _register(system, target)
    listing = connections.list_connections(system.id)
    assert listing
    item = listing[0]
    assert "status" in item
    assert "status_checked_at" in item
    assert "password" not in item
    assert "password_encrypted" not in item


def test_check_connection_health_saudavel(system, target):
    conn = _register(system, target)
    connections.check_connection_health(conn.id)
    listing = connections.list_connections(system.id)
    assert listing[0]["status"] == "healthy"
    assert listing[0]["status_checked_at"] is not None


def test_check_connection_health_degradado(system, target):
    from unittest.mock import patch

    # suprime o thread de provisionamento para evitar PermissionError de background
    with patch("appaiforge.services.connections._refresh_provisioning"):
        conn = connections.register_connection(
            system, "health-degraded", target["host"], target["port"],
            target["database"], target["username"], target["password"],
        )
    with patch("appaiforge.services.connections.psycopg.connect", side_effect=Exception("timeout")):
        connections.check_connection_health(conn.id)
    listing = connections.list_connections(system.id)
    item = next(c for c in listing if c["id"] == conn.id)
    assert item["status"] == "degraded"
    assert item["status_checked_at"] is not None


def test_check_connection_health_nao_levanta_excecao(system, target):
    """check_connection_health nunca deve propagar exceção."""
    from unittest.mock import patch

    with patch("appaiforge.services.connections._refresh_provisioning"):
        conn = connections.register_connection(
            system, "health-nao-levanta", target["host"], target["port"],
            target["database"], target["username"], target["password"],
        )
    with patch("appaiforge.services.connections.psycopg.connect", side_effect=RuntimeError("falha inesperada")):
        connections.check_connection_health(conn.id)  # não deve levantar


def test_list_degraded_connections_retorna_degradadas(system, target):
    from unittest.mock import patch

    with patch("appaiforge.services.connections._refresh_provisioning"):
        conn = connections.register_connection(
            system, "health-deg-list", target["host"], target["port"],
            target["database"], target["username"], target["password"],
        )
    with patch("appaiforge.services.connections.psycopg.connect", side_effect=Exception("timeout")):
        connections.check_connection_health(conn.id)

    degraded = connections.list_degraded_connections()
    assert any(d["id"] == conn.id for d in degraded)


def test_list_degraded_connections_vazia_quando_saudaveis(system, target):
    _register(system, target)
    # nenhum check foi feito: status é 'unknown', não 'degraded'
    degraded = connections.list_degraded_connections()
    assert degraded == []


def test_description_e_access_mode_salvos_e_retornados(system, target):
    conn = connections.register_connection(
        system, "com-meta", target["host"], target["port"], target["database"],
        target["username"], target["password"],
        description="Banco de produção", access_mode="read_only",
    )
    listing = connections.list_connections(system.id)
    item = next(c for c in listing if c["id"] == conn.id)
    assert item["description"] == "Banco de produção"
    assert item["access_mode"] == "read_only"
    assert "password" not in item
    assert "password_encrypted" not in item


def test_defaults_description_none_access_mode_read_write(system, target):
    _register(system, target)
    listing = connections.list_connections(system.id)
    item = listing[0]
    assert item["description"] is None
    assert item["access_mode"] == "read_write"


def test_update_description_e_access_mode(system, target):
    conn = _register(system, target)
    connections.update_connection(
        system, conn.id, "principal", target["host"], target["port"],
        target["database"], target["username"], password=None,
        description="Relatórios", access_mode="read_only",
    )
    listing = connections.list_connections(system.id)
    item = listing[0]
    assert item["description"] == "Relatórios"
    assert item["access_mode"] == "read_only"
