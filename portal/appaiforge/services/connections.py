"""Serviço de conexões de banco (spec db-connections).

Senhas são cifradas em repouso (ADR 0007), nunca retornadas pela interface
e nunca registradas em logs. O teste de conectividade é obrigatório antes de
salvar (spec: conexão inválida é recusada).
"""

import logging

import psycopg
from sqlalchemy import select

from ..db import session_scope
from ..models import DbConnection, System
from ..security import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)


class ConnectionFailed(Exception):
    """Teste de conectividade falhou (host inacessível ou credenciais erradas)."""


class NameTaken(Exception):
    pass


def connection_string(conn: DbConnection, password: str) -> str:
    return f"postgresql://{conn.username}:{password}@{conn.host}:{conn.port}/{conn.database}"


def test_connection(host: str, port: int, database: str, username: str, password: str) -> None:
    """Levanta ConnectionFailed se não conectar; ok caso contrário."""
    try:
        with psycopg.connect(
            host=host, port=port, dbname=database, user=username, password=password,
            connect_timeout=5,
        ) as cx:
            with cx.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except psycopg.OperationalError as exc:
        raise ConnectionFailed(f"não foi possível conectar: {exc.__class__.__name__}") from exc
    except psycopg.errors.AuthenticationFailed as exc:
        raise ConnectionFailed("credenciais recusadas pelo banco") from exc


def register_connection(system: System, name: str, host: str, port: int, database: str, username: str, password: str) -> DbConnection:
    """Testa e cadastra; devolve a conexão SEM o segredo exposto."""
    test_connection(host, port, database, username, password)
    with session_scope() as s:
        exists = s.execute(
            select(DbConnection.id).where(DbConnection.system_id == system.id, DbConnection.name == name.strip())
        ).scalar_one_or_none()
        if exists is not None:
            raise NameTaken(f"conexão '{name}' já existe neste sistema")
        conn = DbConnection(
            system_id=system.id,
            name=name.strip(),
            host=host.strip(),
            port=port,
            database=database.strip(),
            username=username.strip(),
            password_encrypted=encrypt_secret(password),
        )
        s.add(conn)
        s.flush()
        s.expunge(conn)
    log.info("conexão registrada: sistema=%s nome=%s host=%s db=%s", system.slug, conn.name, conn.host, conn.database)
    _refresh_provisioning(system)
    return conn


def list_connections(system_id: str) -> list[dict]:
    """Metadados sem segredo (spec: edição nunca retorna a senha)."""
    with session_scope() as s:
        conns = s.execute(select(DbConnection).where(DbConnection.system_id == system_id)).scalars().all()
        return [_to_safe(c) for c in conns]


def _to_safe(c: DbConnection) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "kind": c.kind,
        "host": c.host,
        "port": c.port,
        "database": c.database,
        "username": c.username,
    }


def get_connection_secret(connection_id: str) -> tuple[DbConnection, str]:
    """Uso interno do provisionamento (env do container); nunca expor à UI."""
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        assert conn is not None
        secret = decrypt_secret(conn.password_encrypted)
        s.expunge(conn)
        return conn, secret


def remove_connection(system: System, connection_id: str) -> None:
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        if conn is not None and conn.system_id == system.id:
            s.delete(conn)
    log.info("conexão removida: sistema=%s id=%s", system.slug, connection_id)
    _refresh_provisioning(system)


def _refresh_provisioning(system: System) -> None:
    """Aplica a mudança de conexões ao provisionamento fora do request."""
    import threading

    def work() -> None:
        try:
            from ..provisioning import refresh_connections

            refresh_connections(system)
        except Exception:
            log.exception("não foi possível aplicar conexões ao container de %s", system.slug)

    threading.Thread(target=work, daemon=True, name=f"refresh-conn-{system.slug}").start()
