"""Quais ações reprovisionam quais sistemas (change add-db-manager-role, task 5.4, design D7).

Passa pelo caminho real — thread de reprovisionamento → `refresh_connections` →
`provision_system` — com um driver falso que guarda o ambiente entregue a cada sistema."""

import threading

import pytest

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import DbConnection, User, UserType
from appaiforge.services import connections
from appaiforge.services.systems import create_system


class _RecordingDriver:
    def __init__(self):
        self.provisioned: list[tuple[str, dict]] = []

    def ensure_ready(self):
        pass

    def provision(self, system, *, env, manifest):
        self.provisioned.append((system.id, {k: v for k, v in env.items() if k.startswith("DATABASE_URL_")}))
        return "fake-unit"

    def remove(self, system):
        pass


@pytest.fixture()
def driver(monkeypatch, tmp_path):
    d = _RecordingDriver()
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("appaiforge.drivers.get_driver", lambda: d)
    monkeypatch.setattr("appaiforge.provisioning.set_container", lambda *a: None)
    monkeypatch.setattr("appaiforge.provisioning.publish_app", lambda *a, **kw: None)
    monkeypatch.setattr("appaiforge.provisioning._provider_env", lambda *a: {})
    monkeypatch.setattr("appaiforge.provisioning.write_agent_profile", lambda *a, **kw: {})
    monkeypatch.setattr("appaiforge.provisioning._check_capacity", lambda *a: None)
    monkeypatch.setattr(connections, "test_connection", lambda *a: None)
    return d


def _settle() -> None:
    for thread in list(threading.enumerate()):
        if thread.name.startswith("refresh-conn-"):
            thread.join(30)


@pytest.fixture()
def ctx(clean_db, driver):
    owner = auth.create_user("dono@rep.local", "pw", UserType.editor.value)
    dba = auth.create_user("dba@rep.local", "pw", UserType.app_user.value)
    with session_scope() as s:
        s.get(User, dba.id).db_manager = True
    dba.db_manager = True
    x = create_system(owner, "X", "rep-x")
    y = create_system(owner, "Y", "rep-y")
    z = create_system(owner, "Z", "rep-z")
    with session_scope() as s:
        conn = DbConnection(name="vendas", kind="postgres", host="db", port=5432, database="vendas",
                            username="app", password_encrypted=connections.encrypt_secret("pw"))
        s.add(conn)
        s.flush()
        conn_id = conn.id
    grants = {}
    for sys_ in (x, y, z):
        grants[sys_.slug] = connections.grant_connection(conn_id, sys_.id, "schema_admin", actor=dba,
                                                         confirmed=True)["grant_id"]
    for sys_, alias in ((x, "vendas"), (y, "erp")):
        connections.activate(sys_, grants[sys_.slug], alias, "read_write", actor=owner)
    _settle()
    driver.provisioned.clear()
    return {"owner": owner, "dba": dba, "x": x, "y": y, "z": z, "conn": conn_id, "grants": grants}


def _provisioned(driver) -> list[str]:
    _settle()
    return [sid for sid, _ in driver.provisioned]


def test_revogar_reprovisiona_so_o_sistema_e_tira_a_variavel(ctx, driver):
    connections.revoke_grant(ctx["grants"]["rep-x"], actor=ctx["dba"])
    assert _provisioned(driver) == [ctx["x"].id]
    assert driver.provisioned[0][1] == {}


def test_desativar_reprovisiona_o_sistema(ctx, driver):
    connections.deactivate(ctx["x"], ctx["grants"]["rep-x"], actor=ctx["owner"])
    assert _provisioned(driver) == [ctx["x"].id]


def test_mudar_modo_reprovisiona_o_sistema(ctx, driver):
    connections.set_mode(ctx["y"], ctx["grants"]["rep-y"], "read_only", actor=ctx["owner"])
    assert _provisioned(driver) == [ctx["y"].id]
    assert set(driver.provisioned[0][1]) == {"DATABASE_URL_ERP"}


def test_editar_credencial_reprovisiona_os_ativos(ctx, driver):
    connections.update_connection(ctx["conn"], "vendas", "db", 5432, "vendas", "app", password="nova",
                                  actor=ctx["dba"])
    assert sorted(_provisioned(driver)) == sorted([ctx["x"].id, ctx["y"].id])  # z está só autorizado


def test_rebaixar_teto_que_reduz_o_modo_reprovisiona(ctx, driver):
    connections.set_mode(ctx["x"], ctx["grants"]["rep-x"], "schema_admin", actor=ctx["owner"])
    _settle()
    driver.provisioned.clear()
    connections.set_ceiling(ctx["grants"]["rep-x"], "read_write", actor=ctx["dba"])
    assert _provisioned(driver) == [ctx["x"].id]


def test_autorizar_nao_reprovisiona(ctx, driver):
    other = create_system(ctx["owner"], "W", "rep-w")
    connections.grant_connection(ctx["conn"], other.id, actor=ctx["dba"])
    assert _provisioned(driver) == []


def test_renomear_no_catalogo_nao_reprovisiona(ctx, driver):
    connections.update_connection(ctx["conn"], "vendas-novo", "db", 5432, "vendas", "app", actor=ctx["dba"])
    assert _provisioned(driver) == []


def test_rebaixar_teto_sem_reduzir_o_modo_nao_reprovisiona(ctx, driver):
    connections.set_ceiling(ctx["grants"]["rep-x"], "read_write", actor=ctx["dba"])
    assert _provisioned(driver) == []
