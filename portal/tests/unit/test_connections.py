"""Unitários do catálogo de conexões (change add-db-manager-role, grupo 3; spec db-connections).

O cadastro exige conexão real, então os testes apontam para o Postgres da sessão (fixture
live_pg). O reprovisionamento é trocado por um registro em memória (`refreshes`): estes testes
não sobem containers.
"""

import json
import logging
from unittest.mock import patch

import pytest
from sqlalchemy import text

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import User, UserType
from appaiforge.services import audit, connections
from appaiforge.services.systems import create_system

SA_JSON = json.dumps({"type": "service_account", "client_email": "sa@proj.iam.gserviceaccount.com"})


@pytest.fixture()
def refreshes(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(connections, "_refresh_systems", lambda ids: calls.append(list(dict.fromkeys(ids))))
    return calls


@pytest.fixture()
def people(clean_db, refreshes):
    admin = auth.create_user("admin@cat.local", "pw", UserType.admin.value)
    editor = auth.create_user("ed@cat.local", "pw", UserType.editor.value)
    dba = auth.create_user("dba@cat.local", "pw", UserType.editor.value)
    dba2 = auth.create_user("dba2@cat.local", "pw", UserType.app_user.value)
    with session_scope() as s:
        s.get(User, dba.id).db_manager = True
        s.get(User, dba2.id).db_manager = True
    dba.db_manager = dba2.db_manager = True
    return {"admin": admin, "editor": editor, "dba": dba, "dba2": dba2}


SECRET = "sup3r-senha-do-banco"


@pytest.fixture()
def target(live_pg):
    """Um usuário próprio no Postgres da sessão, com senha que não se confunde com nenhum outro
    campo — a senha padrão do container (`test`) é também o nome do usuário e do banco."""
    import psycopg

    with psycopg.connect(
        host=live_pg["host"], port=live_pg["port"], dbname=live_pg["database"],
        user=live_pg["username"], password=live_pg["password"], autocommit=True,
    ) as cx:
        exists = cx.execute("SELECT 1 FROM pg_roles WHERE rolname = 'catalogo_app'").fetchone()
        if not exists:
            cx.execute(f"CREATE ROLE catalogo_app LOGIN PASSWORD '{SECRET}'")
    return {**live_pg, "username": "catalogo_app", "password": SECRET}


def _create(target, name="vendas", actor=None, **kw):
    return connections.create_connection(
        name, target["host"], target["port"], target["database"], target["username"], target["password"],
        actor=actor, **kw,
    )


def _stored_password(conn_id):
    with session_scope() as s:
        return s.execute(
            text("SELECT password_encrypted FROM db_connections WHERE id = :id"), {"id": conn_id}
        ).scalar_one()


# --- Catálogo de conexões gerido pelo DB Manager ---

def test_db_manager_cadastra_conexao_sem_autorizacao(people, target):
    conn = _create(target, actor=people["dba"])
    assert conn["name"] == "vendas" and conn["kind"] == "postgres"
    assert connections.connection_systems(conn["id"]) == []


def test_db_manager_cadastra_conexao_mysql(people, monkeypatch):
    monkeypatch.setattr(connections, "_test_mysql", lambda *a: None)
    conn = connections.create_connection("estoque", "mysql-host", 3306, "estoque", "app", "pw", kind="mysql",
                                         actor=people["dba"])
    assert conn["kind"] == "mysql"


def test_admin_cadastra_conexao(people, target):
    assert _create(target, actor=people["admin"])["name"] == "vendas"


def test_dono_de_sistema_nao_cadastra(people, target):
    with pytest.raises(PermissionError):
        _create(target, actor=people["editor"])


def test_nome_repetido_no_catalogo(people, target):
    _create(target, actor=people["dba"])
    with pytest.raises(connections.NameTaken):
        _create(target, actor=people["dba2"])


def test_catalogo_compartilhado_entre_db_managers(people, target):
    conn = _create(target, actor=people["dba"])
    connections.update_connection(
        conn["id"], "vendas-prod", target["host"], target["port"], target["database"], target["username"],
        actor=people["dba2"],
    )
    assert [c["name"] for c in connections.list_catalog()] == ["vendas-prod"]


# --- Teste de conexão antes de salvar ---

def test_conexao_invalida_recusada(people, target):
    with pytest.raises(connections.ConnectionFailed):
        connections.create_connection("ruim", target["host"], target["port"], target["database"],
                                      target["username"], "senha-errada", actor=people["dba"])


def test_edicao_com_credencial_invalida_mantem_a_anterior(people, target):
    conn = _create(target, actor=people["dba"])
    before = _stored_password(conn["id"])
    with pytest.raises(connections.ConnectionFailed):
        connections.update_connection(conn["id"], "vendas", target["host"], target["port"], target["database"],
                                      target["username"], password="senha-errada", actor=people["dba"])
    assert _stored_password(conn["id"]) == before


# --- Credenciais protegidas ---

def test_senha_cifrada_em_repouso(people, target):
    conn = _create(target, actor=people["dba"])
    raw = _stored_password(conn["id"])
    assert target["password"] not in raw
    assert connections.decrypt_secret(raw) == target["password"]


def test_catalogo_nao_expoe_senha(people, target):
    conn = _create(target, actor=people["dba"])
    for item in (connections.list_catalog()[0], connections.get_catalog_connection(conn["id"])):
        assert "password" not in item and "password_encrypted" not in item
        assert target["password"] not in str(item)


def test_logs_nao_contem_senha(people, target, caplog):
    with caplog.at_level(logging.DEBUG, logger="appaiforge.services.connections"):
        conn = _create(target, actor=people["dba"])
        connections.update_connection(conn["id"], "vendas", target["host"], target["port"], target["database"],
                                      target["username"], password=target["password"], actor=people["dba"])
        connections.delete_connection(conn["id"], actor=people["dba"])
    assert target["password"] not in "\n".join(rec.getMessage() for rec in caplog.records)


def test_edicao_senha_vazia_mantem_a_atual(people, target):
    conn = _create(target, actor=people["dba"])
    connections.update_connection(conn["id"], "vendas", target["host"], target["port"], target["database"],
                                  target["username"], password=None, actor=people["dba"])
    assert connections.decrypt_secret(_stored_password(conn["id"])) == target["password"]


def test_edicao_com_senha_troca_a_cifra(people, target):
    conn = _create(target, actor=people["dba"])
    before = _stored_password(conn["id"])
    connections.update_connection(conn["id"], "vendas", target["host"], target["port"], target["database"],
                                  target["username"], password=target["password"], actor=people["dba"])
    after = _stored_password(conn["id"])
    assert after != before
    assert connections.decrypt_secret(after) == target["password"]


# --- Edição de conexão do catálogo ---

def test_tipo_nao_e_editavel(people, target):
    conn = _create(target, actor=people["dba"])
    with pytest.raises(TypeError):
        connections.update_connection(conn["id"], "vendas", target["host"], target["port"], target["database"],
                                      target["username"], kind="mysql", actor=people["dba"])
    assert connections.get_catalog_connection(conn["id"])["kind"] == "postgres"


def test_troca_de_senha_alcanca_todos_os_sistemas_ativos(people, target, refreshes):
    a = create_system(people["editor"], "A", "cat-a")
    b = create_system(people["editor"], "B", "cat-b")
    c = create_system(people["editor"], "C", "cat-c")
    conn = _create(target, actor=people["dba"])
    for sys_ in (a, b, c):
        connections.grant_connection(conn["id"], sys_.id, actor=people["dba"])
    for sys_ in (a, b):
        grant = connections.list_system_connections(sys_.id)[0]
        connections.activate(sys_, grant["grant_id"], "vendas", "read_write", actor=people["editor"])
    refreshes.clear()
    connections.update_connection(conn["id"], "vendas", target["host"], target["port"], target["database"],
                                  target["username"], password=target["password"], actor=people["dba"])
    assert refreshes == [sorted([a.id, b.id], key=[a.id, b.id].index)]


def test_edicao_lista_sistemas_afetados(people, target):
    a = create_system(people["editor"], "A", "cat-la")
    conn = _create(target, actor=people["dba"])
    connections.grant_connection(conn["id"], a.id, actor=people["dba"])
    assert [x["slug"] for x in connections.connection_systems(conn["id"])] == ["cat-la"]


def test_renomear_no_catalogo_nao_reprovisiona(people, target, refreshes):
    a = create_system(people["editor"], "A", "cat-rn")
    conn = _create(target, actor=people["dba"])
    connections.grant_connection(conn["id"], a.id, actor=people["dba"])
    grant = connections.list_system_connections(a.id)[0]
    connections.activate(a, grant["grant_id"], "vendas", "read_write", actor=people["editor"])
    refreshes.clear()
    connections.update_connection(conn["id"], "vendas-novo-nome", target["host"], target["port"],
                                  target["database"], target["username"], actor=people["dba"])
    assert refreshes == []
    assert connections.list_system_connections(a.id)[0]["alias"] == "vendas"


# --- Descrição da conexão no catálogo ---

def test_descricao_visivel_ao_dono(people, target):
    a = create_system(people["editor"], "A", "cat-desc")
    conn = _create(target, actor=people["dba"], description="Banco de produção")
    connections.grant_connection(conn["id"], a.id, actor=people["dba"])
    assert connections.list_system_connections(a.id)[0]["description"] == "Banco de produção"


def test_cadastro_sem_descricao(people, target):
    assert _create(target, actor=people["dba"])["description"] is None


# --- Dados da conexão restritos a quem gere o catálogo (task 3.2) ---

_HIDDEN = ("host", "port", "database", "username")


@pytest.mark.parametrize(
    ("kind", "host", "port", "database", "username", "password"),
    [
        ("postgres", "pg.interno", 5432, "vendas", "app_pg", "pw"),
        ("mysql", "my.interno", 3306, "estoque", "app_my", "pw"),
        ("bigquery", "meu-projeto-gcp", 0, "meu_dataset", "", SA_JSON),
    ],
)
def test_projecao_do_dono_sem_endereco(people, kind, host, port, database, username, password):
    a = create_system(people["editor"], "A", f"cat-proj-{kind}")
    with patch.object(connections, "test_connection", lambda *a: None):
        conn = connections.create_connection(f"c-{kind}", host, port, database, username, password, kind=kind,
                                             actor=people["dba"])
    connections.grant_connection(conn["id"], a.id, actor=people["dba"])
    owner = connections.list_system_connections(a.id)[0]
    for field in _HIDDEN:
        assert field not in owner
    dump = json.dumps(owner)
    for secret in (host, database, "sa@proj.iam.gserviceaccount.com", "app_pg", "app_my"):
        assert secret not in dump
    assert owner["kind"] == kind and owner["name"] == f"c-{kind}"
    # quem gere o catálogo vê o endereço
    catalog = connections.get_catalog_connection(conn["id"])
    assert catalog["host"] == host and catalog["database"] == database


# --- Exclusão de conexão do catálogo ---

def test_exclusao_sem_uso(people, target):
    conn = _create(target, actor=people["dba"])
    assert connections.delete_connection(conn["id"], actor=people["dba"]) == {"systems": [], "rotate_key": False}
    assert connections.list_catalog() == []


def test_exclusao_em_uso_pede_confirmacao(people, target, refreshes):
    a = create_system(people["editor"], "A", "cat-del-a")
    b = create_system(people["editor"], "B", "cat-del-b")
    conn = _create(target, actor=people["dba"])
    for sys_ in (a, b):
        connections.grant_connection(conn["id"], sys_.id, actor=people["dba"])
    with pytest.raises(connections.NeedsConfirmation) as exc:
        connections.delete_connection(conn["id"], actor=people["dba"])
    assert [s["slug"] for s in exc.value.systems] == ["cat-del-a", "cat-del-b"]
    assert len(connections.list_catalog()) == 1


def test_exclusao_revoga_acesso_e_avisa_o_dono(people, target, refreshes):
    a = create_system(people["editor"], "A", "cat-del-r")
    conn = _create(target, actor=people["dba"])
    connections.grant_connection(conn["id"], a.id, actor=people["dba"])
    grant = connections.list_system_connections(a.id)[0]
    connections.activate(a, grant["grant_id"], "vendas", "read_write", actor=people["editor"])
    refreshes.clear()
    connections.delete_connection(conn["id"], actor=people["dba"], confirmed=True)
    assert connections.list_system_connections(a.id) == []
    assert connections.active_connections(a.id) == []
    assert refreshes == [[a.id]]
    [notice] = connections.list_notices(a.id)
    assert notice["kind"] == "connection_deleted" and notice["alias"] == "vendas"


# --- Saúde ---

def test_check_connection_health_saudavel(people, target):
    conn = _create(target, actor=people["dba"])
    connections.check_connection_health(conn["id"])
    item = connections.get_catalog_connection(conn["id"])
    assert item["status"] == "healthy" and item["status_checked_at"] is not None


def test_check_connection_health_degradado(people, target):
    conn = _create(target, actor=people["dba"])
    with patch("appaiforge.services.connections.psycopg.connect", side_effect=Exception("timeout")):
        connections.check_connection_health(conn["id"])
    assert connections.get_catalog_connection(conn["id"])["status"] == "degraded"


def test_check_connection_health_nao_levanta_excecao(people, target):
    conn = _create(target, actor=people["dba"])
    with patch("appaiforge.services.connections.psycopg.connect", side_effect=RuntimeError("falha inesperada")):
        connections.check_connection_health(conn["id"])


def test_nunca_verificada_fica_desconhecida(people, target):
    assert _create(target, actor=people["dba"])["status"] == "unknown"
    assert connections.list_degraded_connections() == []


def test_degradadas_listam_os_sistemas_autorizados(people, target):
    a = create_system(people["editor"], "A", "cat-deg")
    conn = _create(target, actor=people["dba"])
    connections.grant_connection(conn["id"], a.id, actor=people["dba"])
    with patch("appaiforge.services.connections.psycopg.connect", side_effect=Exception("timeout")):
        connections.check_connection_health(conn["id"])
    [degraded] = connections.list_degraded_connections()
    assert degraded["id"] == conn["id"]
    assert [s["slug"] for s in degraded["systems"]] == ["cat-deg"]


def test_saude_uma_vez_por_conexao_inclusive_sem_autorizacao(people, target):
    a = create_system(people["editor"], "A", "cat-h1")
    b = create_system(people["editor"], "B", "cat-h2")
    shared = _create(target, "compartilhada", actor=people["dba"])
    loose = _create(target, "sem-autorizacao", actor=people["dba"])
    for sys_ in (a, b):
        connections.grant_connection(shared["id"], sys_.id, actor=people["dba"])
    checked: list[str] = []
    with patch.object(connections, "check_connection_health", side_effect=checked.append):
        connections.check_all_connections_health()
    assert sorted(checked) == sorted([shared["id"], loose["id"]])


# --- Auditoria (task 3.4) ---

def test_auditoria_do_catalogo_sem_endereco_nem_segredo(people, target):
    conn = _create(target, actor=people["dba"])
    connections.update_connection(conn["id"], "vendas", target["host"], target["port"], target["database"],
                                  target["username"], password=target["password"], actor=people["dba"])
    connections.delete_connection(conn["id"], actor=people["dba"])
    entries = {e["action"]: e for e in audit.list_global(resource_type="connection")}
    assert {"conn.create", "conn.update", "conn.delete"} <= set(entries)
    for entry in entries.values():
        dump = json.dumps(entry["details"])
        assert target["password"] not in dump
        assert target["host"] not in dump
        assert entry["actor_email"] == "dba@cat.local"
        assert entry["system_id"] is None


@pytest.mark.parametrize(
    ("kind", "expected_start"),
    [
        ("postgres", "postgresql://u:pw@h:5432/d"),
        ("mysql", "mysql://u:pw@h:5432/d"),
        ("bigquery", "bigquery://h/d?credentials_base64="),
    ],
)
def test_connection_string_scheme_por_tipo(kind, expected_start):
    from appaiforge.models import DbConnection

    conn = DbConnection(kind=kind, host="h", port=5432, database="d", username="u")
    assert connections.connection_string(conn, "pw").startswith(expected_start)
