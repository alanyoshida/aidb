"""Conftest global dos testes do portal.

Banco de testes: cada sessão sobe um Postgres efêmero via testcontainers
uma única vez e aponta APPAIFORGE_DATABASE_URL para ele (schema limpo por teste
de integração/BDD via drop/create de tabelas).
"""

import os

import pytest

os.environ.setdefault("APPAIFORGE_SECRET_KEY", "test-secret-key")


@pytest.fixture(scope="session")
def database_url():
    from testcontainers.community.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine")
    with container as pg:
        url = pg.get_connection_url(driver="psycopg")
        os.environ["APPAIFORGE_DATABASE_URL"] = url
        from appaiforge.config import get_settings

        get_settings.cache_clear()
        from appaiforge import db as app_db

        app_db.reset_engine()
        yield url
    os.environ.pop("APPAIFORGE_DATABASE_URL", None)


@pytest.fixture()
def clean_db(database_url):
    """Recria o schema (drop+create) para isolamento entre testes."""
    from appaiforge.db import get_engine, reset_engine
    from appaiforge.models import Base

    from appaiforge.installation import reset_cache

    reset_engine()
    reset_cache()
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def live_pg(database_url):
    """Credenciais do Postgres da sessão como alvo de conexão real (host/porta/db/user/senha)."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    return {
        "host": url.host,
        "port": url.port,
        "database": url.database,
        "username": url.username,
        "password": url.password,
    }


@pytest.fixture(autouse=True)
def _isolated_gitdirs(tmp_path_factory, monkeypatch):
    """Repositórios git dos sistemas vivem fora do workspace (change
    `isolate-workspace-repository`); o padrão `/gitdirs` não existe fora do container do portal.
    Cada teste ganha um diretório próprio, separado do de workspaces — testes que definem o seu
    (integração) sobrescrevem este valor depois."""
    monkeypatch.setenv("APPAIFORGE_GITDIRS_DIR", str(tmp_path_factory.mktemp("gitdirs")))


@pytest.fixture(autouse=True)
def _no_lru_settings(database_url):
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def add_active_connection(
    system, alias: str, *, host: str = "db.interno", port: int = 5432, database: str = "app",
    username: str = "app", password: str = "senha", kind: str = "postgres", mode: str = "read_write",
    description: str | None = None, name: str | None = None,
) -> str:
    """Grava uma conexão no catálogo já autorizada e ativa no sistema (change add-db-manager-role),
    sem teste de rede nem reprovisionamento. Devolve o id da conexão."""
    from appaiforge.db import session_scope
    from appaiforge.models import DbConnection, DbConnectionGrant
    from appaiforge.security import encrypt_secret
    from appaiforge.services.connections import env_key

    with session_scope() as s:
        conn = DbConnection(
            name=name or f"{alias} ({system.slug})", kind=kind, host=host, port=port, database=database,
            username=username, password_encrypted=encrypt_secret(password), description=description,
        )
        s.add(conn)
        s.flush()
        s.add(DbConnectionGrant(
            connection_id=conn.id, system_id=system.id, max_mode=mode, mode=mode, active=True,
            alias=alias, alias_key=env_key(alias),
        ))
        return conn.id


@pytest.fixture()
def active_connection():
    """Fábrica de conexões ativas (ver `add_active_connection`)."""
    return add_active_connection


def register_active(system, alias: str, host: str, port: int, database: str, username: str, password: str,
                    kind: str = "postgres", description: str | None = None, mode: str = "read_write") -> dict:
    """Caminho real do catálogo (change add-db-manager-role): testa e cadastra a conexão, autoriza
    para o sistema com teto igual ao modo e ativa com o alias — o que dispara o reprovisionamento,
    como o antigo cadastro por sistema fazia. Devolve a conexão do catálogo."""
    from appaiforge.services import connections

    conn = connections.create_connection(
        f"{alias} ({system.slug})", host, port, database, username, password, kind=kind, description=description,
    )
    grant = connections.grant_connection(conn["id"], system.id, mode, confirmed=True)
    connections.activate(system, grant["grant_id"], alias, mode)
    return conn


@pytest.fixture()
def register_connection():
    """Fábrica de conexões ativas pelo serviço real (ver `register_active`)."""
    return register_active
