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

    reset_engine()
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
def _no_lru_settings(database_url):
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
