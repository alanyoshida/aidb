"""Unitários: reconcile() chama check_connection_health para sistemas ativos,
não chama para arquivados nem para sistemas em provisionamento (task 3.1)."""

from unittest.mock import MagicMock, call, patch

import pytest

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import DbConnection, SystemStatus, UserType
from appaiforge.services import connections
from appaiforge.services.systems import create_system


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("rec@test.local", "pw", UserType.editor.value)


def _make_system(editor, name, slug):
    return create_system(editor, name, slug)


def _set_status(system_id: str, status: SystemStatus) -> None:
    from appaiforge.services.systems import set_status
    set_status(system_id, status, "")


def _add_connection(system, target) -> str:
    conn = connections.register_connection(
        system, "db", target["host"], target["port"], target["database"], target["username"], target["password"]
    )
    return conn.id


@pytest.fixture()
def target(live_pg):
    return live_pg


def test_reconcile_chama_health_para_sistema_ativo(editor, target):
    system = _make_system(editor, "Ativo", "rec-ativo")
    _set_status(system.id, SystemStatus.active)
    conn_id = _add_connection(system, target)

    called = []

    def fake_check(cid):
        called.append(cid)

    with (
        patch("appaiforge.provisioning._docker") as mock_docker,
        patch("appaiforge.provisioning.publish_app_by_slug"),
        patch("appaiforge.services.connections.check_connection_health", side_effect=fake_check),
        patch("appaiforge.provisioning._check_connections_health", side_effect=lambda sid: [fake_check(conn_id) for _ in [None]]),
    ):
        mock_docker.return_value.containers.get.return_value = MagicMock()
        from appaiforge.provisioning import reconcile
        reconcile()

    assert conn_id in called


def test_reconcile_nao_chama_health_para_arquivado(editor, target):
    system = _make_system(editor, "Arquivado", "rec-arch")
    _add_connection(system, target)
    _set_status(system.id, SystemStatus.archived)

    called = []

    def fake_check(cid):
        called.append(cid)

    with (
        patch("appaiforge.provisioning._docker") as mock_docker,
        patch("appaiforge.provisioning.publish_app_by_slug"),
        patch("appaiforge.provisioning._check_connections_health", side_effect=lambda sid: called.append(("health", sid))),
    ):
        mock_docker.return_value.containers.get.return_value = MagicMock()
        from appaiforge.provisioning import reconcile
        reconcile()

    assert not called, "arquivado não deve ter health check chamado"


def test_reconcile_nao_chama_health_para_provisionando(editor, target):
    system = _make_system(editor, "Prov", "rec-prov")
    _add_connection(system, target)
    _set_status(system.id, SystemStatus.provisioning)

    called = []

    with (
        patch("appaiforge.provisioning._docker") as mock_docker,
        patch("appaiforge.provisioning.publish_app_by_slug"),
        patch("appaiforge.provisioning._check_connections_health", side_effect=lambda sid: called.append(("health", sid))),
    ):
        mock_docker.return_value.containers.get.return_value = MagicMock()
        from appaiforge.provisioning import reconcile
        reconcile()

    assert not called, "provisioning não deve ter health check chamado"
