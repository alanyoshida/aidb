"""Integração: teste de conectividade real contra Postgres efêmero (task 3.2)."""

import pytest

from appaiforge.services import connections

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def target_pg():
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield {
            "host": pg.get_container_host_ip(),
            "port": int(pg.get_exposed_port(5432)),
            "database": pg.dbname,
            "username": pg.username,
            "password": pg.password,
        }


def test_conexao_valida_e_aceita(target_pg):
    # não levanta
    connections.test_connection(**target_pg)


def test_credenciais_erradas_sao_recusadas(target_pg):
    with pytest.raises(connections.ConnectionFailed):
        connections.test_connection(**{**target_pg, "password": "errada"})


def test_host_inacessivel_e_recusado(target_pg):
    with pytest.raises(connections.ConnectionFailed):
        connections.test_connection(**{**target_pg, "port": 1})


def test_cadastro_exige_conexao_valida(clean_db, target_pg):
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("live@conn.local", "pw", UserType.editor.value)
    system = create_system(editor, "Live", "live-conn")

    with pytest.raises(connections.ConnectionFailed):
        connections.register_connection(system, "ruim", target_pg["host"], target_pg["port"], target_pg["database"], target_pg["username"], "errada")

    conn = connections.register_connection(system, "boa", target_pg["host"], target_pg["port"], target_pg["database"], target_pg["username"], target_pg["password"])
    assert conn.name == "boa"
