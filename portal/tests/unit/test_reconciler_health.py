"""Unitários: a reconciliação checa a saúde das conexões do catálogo uma vez por passada, uma
vez por conexão — inclusive as que nenhum sistema usa (change add-db-manager-role, D11)."""

from unittest.mock import MagicMock, patch

import pytest

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import DbConnection, DbConnectionGrant, SystemStatus, UserType
from appaiforge.services.systems import create_system, set_status


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("rec@test.local", "pw", UserType.editor.value)


def _connection(name: str) -> str:
    with session_scope() as s:
        conn = DbConnection(name=name, kind="postgres", host="db", port=5432, database="d",
                            username="u", password_encrypted="x")
        s.add(conn)
        s.flush()
        return conn.id


def _grant(conn_id: str, system_id: str) -> None:
    with session_scope() as s:
        s.add(DbConnectionGrant(connection_id=conn_id, system_id=system_id, active=True,
                                alias="db", alias_key="DB", mode="read_write", max_mode="read_write"))


def _reconcile(checked: list[str]) -> None:
    with (
        patch("appaiforge.provisioning._docker") as mock_docker,
        patch("appaiforge.provisioning.publish_app_by_slug"),
        patch("appaiforge.services.connections.check_connection_health", side_effect=checked.append),
    ):
        mock_docker.return_value.containers.get.return_value = MagicMock()
        from appaiforge.provisioning import reconcile

        reconcile()


def test_reconcile_checa_cada_conexao_uma_vez(editor):
    a = create_system(editor, "A", "rec-a")
    b = create_system(editor, "B", "rec-b")
    for sys_ in (a, b):
        set_status(sys_.id, SystemStatus.active, "")
    shared = _connection("compartilhada")
    _grant(shared, a.id)
    _grant(shared, b.id)
    checked: list[str] = []
    _reconcile(checked)
    assert checked == [shared]


def test_reconcile_checa_conexao_sem_autorizacao(editor):
    loose = _connection("solta")
    checked: list[str] = []
    _reconcile(checked)
    assert checked == [loose]


def test_reconcile_checa_conexao_de_sistema_arquivado(editor):
    # a saúde é do catálogo, não do sistema: o DB Manager vê o estado de toda conexão
    system = create_system(editor, "Arq", "rec-arq")
    set_status(system.id, SystemStatus.archived, "")
    conn = _connection("de-arquivado")
    _grant(conn, system.id)
    checked: list[str] = []
    _reconcile(checked)
    assert checked == [conn]


def test_falha_na_checagem_nao_derruba_a_passada(editor):
    _connection("x")
    with (
        patch("appaiforge.provisioning._docker"),
        patch("appaiforge.services.connections.check_all_connections_health", side_effect=RuntimeError("boom")),
    ):
        from appaiforge.provisioning import reconcile

        reconcile()
