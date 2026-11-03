"""Serviço de conexões de banco (spec db-connections).

Senhas são cifradas em repouso (ADR 0007), nunca retornadas pela interface
e nunca registradas em logs. O teste de conectividade é obrigatório antes de
salvar (spec: conexão inválida é recusada).
"""

import base64
import json
import logging

import psycopg
from sqlalchemy import select

from ..db import session_scope
from ..models import DbConnection, System, User
from ..rbac import can_manage_system
from ..security import decrypt_secret, encrypt_secret
from . import audit

log = logging.getLogger(__name__)


class ConnectionFailed(Exception):
    """Teste de conectividade falhou (host inacessível ou credenciais erradas)."""


class NameTaken(Exception):
    pass


class NotFound(Exception):
    pass


_SCHEMES = {"postgres": "postgresql", "mysql": "mysql"}


def connection_string(conn: DbConnection, password: str) -> str:
    if conn.kind == "bigquery":
        b64 = base64.urlsafe_b64encode(password.encode()).decode()
        return f"bigquery://{conn.host}/{conn.database}?credentials_base64={b64}"
    scheme = _SCHEMES.get(conn.kind, "postgresql")
    return f"{scheme}://{conn.username}:{password}@{conn.host}:{conn.port}/{conn.database}"


def test_connection(kind: str, host: str, port: int, database: str, username: str, password: str) -> None:
    """Levanta ConnectionFailed se não conectar; ok caso contrário."""
    if kind == "bigquery":
        _test_bigquery(host, database, password)
    elif kind == "mysql":
        _test_mysql(host, port, database, username, password)
    else:
        _test_postgres(host, port, database, username, password)


def _test_postgres(host: str, port: int, database: str, username: str, password: str) -> None:
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


def _test_bigquery(project: str, dataset: str, sa_json: str) -> None:
    import os
    try:
        from google.cloud import bigquery
        if os.environ.get("BIGQUERY_EMULATOR_HOST"):
            import google.auth.credentials
            creds: object = google.auth.credentials.AnonymousCredentials()
        else:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                json.loads(sa_json),
                scopes=["https://www.googleapis.com/auth/bigquery.readonly"],
            )
        client = bigquery.Client(project=project, credentials=creds)
        list(client.query(
            f"SELECT 1 FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES` LIMIT 1"
        ).result())
    except json.JSONDecodeError as exc:
        raise ConnectionFailed("Service Account JSON inválido") from exc
    except Exception as exc:
        raise ConnectionFailed(f"não foi possível conectar ao BigQuery: {exc.__class__.__name__}") from exc


def _test_mysql(host: str, port: int, database: str, username: str, password: str) -> None:
    import pymysql
    try:
        cx = pymysql.connect(
            host=host, port=port, database=database, user=username, password=password,
            connect_timeout=5,
        )
        cx.close()
    except pymysql.OperationalError as exc:
        raise ConnectionFailed(f"não foi possível conectar: {exc.__class__.__name__}") from exc


def _extract_sa_email(sa_json: str) -> str:
    """Extrai client_email do Service Account JSON; retorna string vazia em caso de falha."""
    try:
        return json.loads(sa_json).get("client_email", "")
    except Exception:
        return ""


def register_connection(
    system: System, name: str, host: str, port: int, database: str, username: str, password: str,
    kind: str = "postgres", actor: User | None = None,
    description: str | None = None, access_mode: str = "read_write",
) -> DbConnection:
    """Testa e cadastra; devolve a conexão SEM o segredo exposto."""
    if actor is not None and not can_manage_system(actor, system):
        raise PermissionError("permissão insuficiente para gerenciar conexões deste sistema")
    test_connection(kind, host, port, database, username, password)
    effective_username = _extract_sa_email(password) if kind == "bigquery" else username.strip()
    with session_scope() as s:
        exists = s.execute(
            select(DbConnection.id).where(DbConnection.system_id == system.id, DbConnection.name == name.strip())
        ).scalar_one_or_none()
        if exists is not None:
            raise NameTaken(f"conexão '{name}' já existe neste sistema")
        conn = DbConnection(
            system_id=system.id,
            name=name.strip(),
            kind=kind,
            host=host.strip(),
            port=port,
            database=database.strip(),
            username=effective_username,
            password_encrypted=encrypt_secret(password),
            description=description.strip() if description else None,
            access_mode=access_mode,
        )
        s.add(conn)
        s.flush()
        s.expunge(conn)
    log.info("conexão registrada: sistema=%s nome=%s host=%s db=%s", system.slug, conn.name, conn.host, conn.database)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="conn.create", resource_type="connection",
        resource_id=conn.id, system_id=system.id,
        details={"name": conn.name, "host": conn.host, "database": conn.database},
    )
    _refresh_provisioning(system)
    return conn


def update_connection(
    system: System, connection_id: str, name: str, host: str, port: int, database: str, username: str,
    password: str | None = None, kind: str | None = None, actor: User | None = None,
    description: str | None = None, access_mode: str | None = None,
) -> DbConnection:
    """Edita uma conexão. Senha vazia mantém a atual; preenchida testa e troca."""
    if actor is not None and not can_manage_system(actor, system):
        raise PermissionError("permissão insuficiente para gerenciar conexões deste sistema")
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        if conn is None or conn.system_id != system.id:
            raise NotFound("conexão não encontrada neste sistema")
        current_password = decrypt_secret(conn.password_encrypted)
        current_kind = conn.kind
        s.expunge(conn)
    effective_password = password if password else current_password
    effective_kind = kind if kind is not None else current_kind
    test_connection(effective_kind, host, port, database, username, effective_password)
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        assert conn is not None
        clean_name = name.strip()
        conflict = s.execute(
            select(DbConnection.id).where(
                DbConnection.system_id == system.id,
                DbConnection.name == clean_name,
                DbConnection.id != connection_id,
            )
        ).scalar_one_or_none()
        if conflict is not None:
            raise NameTaken(f"conexão '{clean_name}' já existe neste sistema")
        effective_username = (
            _extract_sa_email(effective_password) if effective_kind == "bigquery" else username.strip()
        )
        conn.name = clean_name
        conn.kind = effective_kind
        conn.host = host.strip()
        conn.port = port
        conn.database = database.strip()
        conn.username = effective_username
        if password:
            conn.password_encrypted = encrypt_secret(password)
        if description is not None:
            conn.description = description.strip() if description else None
        if access_mode is not None:
            conn.access_mode = access_mode
        s.flush()
        s.expunge(conn)
    log.info("conexão atualizada: sistema=%s id=%s", system.slug, connection_id)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="conn.update", resource_type="connection",
        resource_id=connection_id, system_id=system.id,
        details={"name": clean_name, "host": host.strip(), "database": database.strip(), "password_changed": bool(password)},
    )
    _refresh_provisioning(system)
    return conn


def list_connections(system_id: str) -> list[dict]:
    """Metadados sem segredo (spec: edição nunca retorna a senha)."""
    with session_scope() as s:
        conns = s.execute(select(DbConnection).where(DbConnection.system_id == system_id)).scalars().all()
        return [_to_safe(c) for c in conns]


def list_degraded_connections() -> list[dict]:
    """Retorna todas as conexões degradadas com slug do sistema, para painel admin."""
    from ..models import System

    with session_scope() as s:
        rows = s.execute(
            select(DbConnection, System.slug, System.name)
            .join(System, System.id == DbConnection.system_id)
            .where(DbConnection.status == "degraded")
            .order_by(System.slug, DbConnection.name)
        ).all()
        return [
            {**_to_safe(c), "system_slug": slug, "system_name": sname}
            for c, slug, sname in rows
        ]


def check_connection_health(conn_id: str) -> None:
    """Testa a conexão com timeout de 2s e atualiza status; nunca levanta exceção."""
    from ..models import utcnow

    with session_scope() as s:
        conn = s.get(DbConnection, conn_id)
        if conn is None:
            return
        kind = conn.kind
        host = conn.host
        port = conn.port
        database = conn.database
        username = conn.username
        secret = decrypt_secret(conn.password_encrypted)

    new_status = "unknown"
    try:
        _test_connection_2s(kind, host, port, database, username, secret)
        new_status = "healthy"
    except Exception:
        new_status = "degraded"

    with session_scope() as s:
        conn = s.get(DbConnection, conn_id)
        if conn is not None:
            conn.status = new_status
            conn.status_checked_at = utcnow()


def _test_connection_2s(kind: str, host: str, port: int, database: str, username: str, password: str) -> None:
    """Como test_connection mas com timeout de 2s."""
    if kind == "bigquery":
        _test_bigquery(host, database, password)
    elif kind == "mysql":
        import pymysql
        cx = pymysql.connect(
            host=host, port=port, database=database, user=username, password=password,
            connect_timeout=2,
        )
        cx.close()
    else:
        with psycopg.connect(
            host=host, port=port, dbname=database, user=username, password=password,
            connect_timeout=2,
        ) as cx:
            with cx.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()


def _to_safe(c: DbConnection) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "kind": c.kind,
        "host": c.host,
        "port": c.port,
        "database": c.database,
        "username": c.username,
        "description": c.description,
        "access_mode": c.access_mode,
        "status": c.status,
        "status_checked_at": c.status_checked_at.isoformat() if c.status_checked_at else None,
    }


def get_connection_secret(connection_id: str) -> tuple[DbConnection, str]:
    """Uso interno do provisionamento (env do container); nunca expor à UI."""
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        assert conn is not None
        secret = decrypt_secret(conn.password_encrypted)
        s.expunge(conn)
        return conn, secret


def remove_connection(system: System, connection_id: str, actor: User | None = None) -> None:
    if actor is not None and not can_manage_system(actor, system):
        raise PermissionError("permissão insuficiente para gerenciar conexões deste sistema")
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        if conn is not None and conn.system_id == system.id:
            s.delete(conn)
    log.info("conexão removida: sistema=%s id=%s", system.slug, connection_id)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="conn.remove", resource_type="connection",
        resource_id=connection_id, system_id=system.id, details={},
    )
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
