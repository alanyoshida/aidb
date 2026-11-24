"""Serviço de conexões de banco (specs db-connections, db-connection-access).

Desde a change add-db-manager-role (ADR 0036) as conexões formam um catálogo único, gerido por
quem tem a capacidade de DB Manager (ou por um admin). Uma conexão chega a um sistema por uma
autorização (`DbConnectionGrant`), com teto de modo de acesso, e só é entregue ao agente e à app
depois que quem gerencia o sistema a ativa, escolhendo alias e modo.

Senhas são cifradas em repouso (ADR 0007), nunca retornadas pela interface
e nunca registradas em logs. O teste de conectividade é obrigatório antes de
salvar (spec: conexão inválida é recusada).
"""

import base64
import json
import logging
import re
from dataclasses import dataclass

import psycopg
from sqlalchemy import select

from ..db import session_scope
from ..models import (
    ACCESS_MODES,
    DbConnection,
    DbConnectionGrant,
    System,
    SystemConnectionNotice,
    User,
    utcnow,
)
from ..rbac import can_manage_catalog, can_manage_system
from ..security import decrypt_secret, encrypt_secret
from . import audit

log = logging.getLogger(__name__)


class ConnectionFailed(Exception):
    """Teste de conectividade falhou (host inacessível ou credenciais erradas)."""


class NameTaken(Exception):
    pass


class NotFound(Exception):
    pass


class GrantExists(Exception):
    """A conexão já está autorizada para o sistema."""


class InvalidAlias(ValueError):
    pass


class AliasTaken(Exception):
    pass


class InvalidMode(ValueError):
    """Modo desconhecido, acima do teto ou que não se aplica ao tipo da conexão."""


class NeedsConfirmation(Exception):
    """A ação afeta outros sistemas e precisa ser confirmada; `systems` lista quais."""

    def __init__(self, message: str, systems: list[dict]):
        super().__init__(message)
        self.systems = systems


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


def _connection_failed(exc: Exception, password: str) -> ConnectionFailed:
    """Mensagem do driver (host, porta e motivo), que o nome da classe sozinho omite.

    O texto vai para a tela, então a senha é removida caso o driver a inclua.
    """
    detail = str(exc).strip() or exc.__class__.__name__
    if password and password in detail:
        detail = detail.replace(password, "***")
    return ConnectionFailed(f"não foi possível conectar: {detail}")


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
        raise _connection_failed(exc, password) from exc
    except psycopg.errors.AuthenticationFailed as exc:
        raise ConnectionFailed("credenciais recusadas pelo banco") from exc


def _test_bigquery(project: str, dataset: str, sa_json: str) -> None:
    """Valida o Service Account JSON e o acesso ao dataset (spec db-bigquery).

    O JSON é validado sempre, inclusive com o emulador (antes, no emulador ele nem era lido).
    O acesso é verificado com `get_dataset` em vez de uma query: confirma credencial, projeto e
    dataset sem custo de execução, e funciona no emulador do E2E — que não suporta
    INFORMATION_SCHEMA e devolvia `jobInternalError`, que o client tratava como recuperável e
    recriava o job indefinidamente."""
    import os

    try:
        info = json.loads(sa_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ConnectionFailed("Service Account JSON inválido") from exc
    if not isinstance(info, dict) or not info.get("client_email"):
        raise ConnectionFailed("Service Account JSON inválido")
    try:
        from google.cloud import bigquery
        if os.environ.get("BIGQUERY_EMULATOR_HOST"):
            import google.auth.credentials
            creds: object = google.auth.credentials.AnonymousCredentials()
        else:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/bigquery.readonly"],
            )
        client = bigquery.Client(project=project, credentials=creds)
        client.get_dataset(f"{project}.{dataset}", timeout=15)
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
        raise _connection_failed(exc, password) from exc




def _extract_sa_email(sa_json: str) -> str:
    """Extrai client_email do Service Account JSON; retorna string vazia em caso de falha."""
    try:
        return json.loads(sa_json).get("client_email", "")
    except Exception:
        return ""


# --- Modos e alias (design D4, D5) ---------------------------------------------------------

_MODE_RANK = {mode: i for i, mode in enumerate(ACCESS_MODES)}
_ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
MODE_LABELS = {
    "read_only": "Somente leitura",
    "read_write": "Leitura e escrita",
    "schema_admin": "Leitura, escrita e DDL",
}


def env_key(name: str) -> str:
    """Nome normalizado que vira o sufixo de `DATABASE_URL_<...>`."""
    return re.sub(r"[^A-Z0-9]", "_", name.upper())


def modes_for(kind: str) -> tuple[str, ...]:
    """Modos que fazem sentido para o tipo: BigQuery não tem `schema_admin` (spec db-bigquery)."""
    return ACCESS_MODES[:2] if kind == "bigquery" else ACCESS_MODES


def _check_mode(mode: str, kind: str) -> None:
    if mode not in ACCESS_MODES:
        raise InvalidMode(f"modo de acesso inválido: {mode}")
    if mode not in modes_for(kind):
        raise InvalidMode(f"o modo {mode} não se aplica a BigQuery")


def suggest_alias(name: str) -> str:
    """Alias sugerido a partir do nome no catálogo, já no formato aceito: sem acento, minúsculo,
    o resto vira hífen (`Estoque legado` -> `estoque-legado`)."""
    import unicodedata

    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9_-]+", "-", ascii_name.lower()).strip("-")
    return slug[:120] or "banco"


def _validate_alias(alias: str) -> str:
    clean = (alias or "").strip()
    if not _ALIAS_RE.match(clean):
        raise InvalidAlias("o alias aceita só letras, dígitos, hífen e sublinhado (até 120)")
    return clean


def _actor_fields(actor: User | None) -> dict:
    return {"actor_id": actor.id if actor else None, "actor_email": actor.email if actor else None}


def _require_catalog(actor: User | None) -> None:
    if actor is not None and not can_manage_catalog(actor):
        raise PermissionError("operação restrita a DB Managers e administradores")


def _require_system_manager(actor: User | None, system: System) -> None:
    if actor is not None and not can_manage_system(actor, system):
        raise PermissionError("permissão insuficiente para gerenciar conexões deste sistema")


# --- Projeções (design D3, spec "Dados da conexão restritos a quem gere o catálogo") ---------

def _status_fields(c: DbConnection) -> dict:
    return {
        "status": c.status,
        "status_checked_at": c.status_checked_at.isoformat() if c.status_checked_at else None,
    }


def _catalog_view(c: DbConnection) -> dict:
    """Para quem gere o catálogo: endereço e usuário, nunca a senha."""
    return {
        "id": c.id,
        "name": c.name,
        "kind": c.kind,
        "host": c.host,
        "port": c.port,
        "database": c.database,
        "username": c.username,
        "description": c.description,
        **_status_fields(c),
    }


def _owner_view(g: DbConnectionGrant, c: DbConnection) -> dict:
    """Para quem gerencia o sistema: nada de host, porta, banco, usuário ou credencial."""
    return {
        "grant_id": g.id,
        "connection_id": c.id,
        "name": c.name,
        "description": c.description,
        "kind": c.kind,
        **_status_fields(c),
        "max_mode": g.max_mode,
        "modes": [m for m in modes_for(c.kind) if _MODE_RANK[m] <= _MODE_RANK[g.max_mode]],
        "active": g.active,
        "alias": g.alias if g.active else None,
        # O alias anterior volta como sugestão; um vindo da migração fora do formato (o nome
        # antigo, ex. `Estoque legado`) vira um aceito com a mesma variável de ambiente.
        "suggested_alias": (g.alias if g.alias and _ALIAS_RE.match(g.alias)
                            else suggest_alias(g.alias or c.name)),
        "mode": g.mode,
        "schema_admin_since": g.schema_admin_since.isoformat() if g.active and g.schema_admin_since else None,
    }


# --- Catálogo -------------------------------------------------------------------------------

def list_catalog() -> list[dict]:
    """Todas as conexões do catálogo, com quantos sistemas as têm autorizadas e ativas."""
    with session_scope() as s:
        conns = s.execute(select(DbConnection).order_by(DbConnection.name)).scalars().all()
        grants = s.execute(select(DbConnectionGrant)).scalars().all()
        out = []
        for c in conns:
            mine = [g for g in grants if g.connection_id == c.id]
            out.append({
                **_catalog_view(c),
                "granted_count": len(mine),
                "active_count": sum(1 for g in mine if g.active),
            })
        return out


def get_catalog_connection(connection_id: str) -> dict:
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        if conn is None:
            raise NotFound("conexão não encontrada no catálogo")
        return _catalog_view(conn)


def create_connection(
    name: str, host: str, port: int, database: str, username: str, password: str,
    kind: str = "postgres", description: str | None = None, actor: User | None = None,
) -> dict:
    """Testa e cadastra no catálogo; a conexão nasce sem autorização para nenhum sistema."""
    _require_catalog(actor)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("informe o nome da conexão")
    test_connection(kind, host, port, database, username, password)
    effective_username = _extract_sa_email(password) if kind == "bigquery" else username.strip()
    with session_scope() as s:
        if s.execute(select(DbConnection.id).where(DbConnection.name == clean_name)).scalar_one_or_none():
            raise NameTaken(f"já existe uma conexão chamada '{clean_name}' no catálogo")
        conn = DbConnection(
            name=clean_name,
            kind=kind,
            host=host.strip(),
            port=port,
            database=database.strip(),
            username=effective_username,
            password_encrypted=encrypt_secret(password),
            description=description.strip() if description else None,
        )
        s.add(conn)
        s.flush()
        view = _catalog_view(conn)
    log.info("conexão cadastrada no catálogo: nome=%s host=%s db=%s", view["name"], view["host"], view["database"])
    audit.record(
        **_actor_fields(actor), action="conn.create", resource_type="connection", resource_id=view["id"],
        details={"name": view["name"], "kind": kind},
    )
    return view


def connection_systems(connection_id: str) -> list[dict]:
    """Sistemas com autorização para a conexão (para confirmações de edição e exclusão)."""
    with session_scope() as s:
        rows = s.execute(
            select(DbConnectionGrant, System)
            .join(System, System.id == DbConnectionGrant.system_id)
            .where(DbConnectionGrant.connection_id == connection_id)
            .order_by(System.slug)
        ).all()
        return [
            {"system_id": sys_.id, "slug": sys_.slug, "name": sys_.name, "active": g.active, "alias": g.alias}
            for g, sys_ in rows
        ]


def update_connection(
    connection_id: str, name: str, host: str, port: int, database: str, username: str,
    password: str | None = None, description: str | None = None, actor: User | None = None,
) -> dict:
    """Edita uma conexão do catálogo. Senha vazia mantém a atual. Endereço ou credencial novos
    são testados antes de salvar e passam a valer na hora em todo sistema onde a conexão está
    ativa. O tipo não muda (D3)."""
    _require_catalog(actor)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("informe o nome da conexão")
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        if conn is None:
            raise NotFound("conexão não encontrada no catálogo")
        kind = conn.kind
        current_password = decrypt_secret(conn.password_encrypted)
        before = (conn.host, conn.port, conn.database, conn.username, conn.description)
    new_host, new_db = host.strip(), database.strip()
    effective_password = password if password else current_password
    effective_username = _extract_sa_email(effective_password) if kind == "bigquery" else username.strip()
    address_changed = (
        bool(password) or (new_host, port, new_db, effective_username) != before[:4]
    )
    new_description = description.strip() if description else None
    if address_changed:
        test_connection(kind, new_host, port, new_db, username, effective_password)
    with session_scope() as s:
        conflict = s.execute(
            select(DbConnection.id).where(DbConnection.name == clean_name, DbConnection.id != connection_id)
        ).scalar_one_or_none()
        if conflict is not None:
            raise NameTaken(f"já existe uma conexão chamada '{clean_name}' no catálogo")
        conn = s.get(DbConnection, connection_id)
        assert conn is not None
        conn.name = clean_name
        conn.host = new_host
        conn.port = port
        conn.database = new_db
        conn.username = effective_username
        if password:
            conn.password_encrypted = encrypt_secret(password)
        conn.description = new_description
        view = _catalog_view(conn)
    log.info("conexão do catálogo atualizada: id=%s", connection_id)
    audit.record(
        **_actor_fields(actor), action="conn.update", resource_type="connection", resource_id=connection_id,
        details={"name": clean_name, "address_changed": address_changed, "password_changed": bool(password)},
    )
    # O que o container recebe muda com endereço/credencial e com a descrição (rótulo da
    # ferramenta do agente); renomear no catálogo não muda nada (D7).
    if address_changed or new_description != before[4]:
        _refresh_systems(_active_system_ids(connection_id))
    return view


def delete_connection(connection_id: str, actor: User | None = None, confirmed: bool = False) -> dict:
    """Exclui do catálogo. Com autorizações, exige confirmação e revoga todas na hora.

    Devolve `{"systems": [...], "rotate_key": bool}` — `rotate_key` avisa que, num BigQuery que
    estava ativo, a chave já entregue só é invalidada ao ser rotacionada no GCP."""
    _require_catalog(actor)
    affected = connection_systems(connection_id)
    if affected and not confirmed:
        raise NeedsConfirmation("a conexão está autorizada para sistemas; confirme a exclusão", affected)
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        if conn is None:
            raise NotFound("conexão não encontrada no catálogo")
        name, kind = conn.name, conn.kind
        grants = s.execute(
            select(DbConnectionGrant).where(DbConnectionGrant.connection_id == connection_id)
        ).scalars().all()
        active_ids = [g.system_id for g in grants if g.active]
        for g in grants:
            if g.active:
                _notice(s, g.system_id, "connection_deleted", name, g.alias,
                        "a conexão foi excluída do catálogo e deixou de ser entregue ao sistema", actor)
            s.delete(g)
        s.flush()
        s.delete(conn)
    log.info("conexão excluída do catálogo: id=%s", connection_id)
    audit.record(
        **_actor_fields(actor), action="conn.delete", resource_type="connection", resource_id=connection_id,
        details={"name": name, "systems": [a["slug"] for a in affected]},
    )
    for a in affected:
        audit.record(
            **_actor_fields(actor), action="conn.revoke", resource_type="connection", resource_id=connection_id,
            system_id=a["system_id"], details={"name": name, "alias": a["alias"], "reason": "connection_deleted"},
        )
    _refresh_systems(active_ids)
    return {"systems": affected, "rotate_key": kind == "bigquery" and bool(active_ids)}


# --- Autorização (quem gere o catálogo) -----------------------------------------------------

def list_systems_for_grant() -> list[dict]:
    """Todos os sistemas, só com nome, slug e dono — o que basta para escolher (spec "Sistemas
    visíveis ao autorizar"). Não concede acesso a nada do sistema."""
    with session_scope() as s:
        rows = s.execute(
            select(System, User.email).join(User, User.id == System.owner_id).order_by(System.slug)
        ).all()
        return [{"id": sys_.id, "slug": sys_.slug, "name": sys_.name, "owner_email": email} for sys_, email in rows]


def list_grants(connection_id: str) -> list[dict]:
    """Autorizações de uma conexão, para a página do catálogo."""
    with session_scope() as s:
        rows = s.execute(
            select(DbConnectionGrant, System, User.email)
            .join(System, System.id == DbConnectionGrant.system_id)
            .join(User, User.id == System.owner_id)
            .where(DbConnectionGrant.connection_id == connection_id)
            .order_by(System.slug)
        ).all()
        return [
            {
                "grant_id": g.id, "system_id": sys_.id, "slug": sys_.slug, "system_name": sys_.name,
                "owner_email": email, "max_mode": g.max_mode, "active": g.active,
                "alias": g.alias if g.active else None, "mode": g.mode,
                "schema_admin_since": g.schema_admin_since.isoformat() if g.active and g.schema_admin_since else None,
                "granted_by_email": g.granted_by_email,
            }
            for g, sys_, email in rows
        ]


def _other_systems(s, connection_id: str, system_id: str) -> list[dict]:
    rows = s.execute(
        select(System.id, System.slug, System.name)
        .join(DbConnectionGrant, DbConnectionGrant.system_id == System.id)
        .where(DbConnectionGrant.connection_id == connection_id, System.id != system_id)
        .order_by(System.slug)
    ).all()
    return [{"system_id": sid, "slug": slug, "name": name} for sid, slug, name in rows]


def _confirm_schema_admin(s, connection_id: str, system_id: str, max_mode: str, confirmed: bool) -> None:
    if max_mode != "schema_admin" or confirmed:
        return
    others = _other_systems(s, connection_id, system_id)
    if others:
        raise NeedsConfirmation(
            "a mesma conexão está autorizada para outros sistemas; uma DDL deste sistema pode afetá-los",
            others,
        )


def grant_connection(
    connection_id: str, system_id: str, max_mode: str = "read_write", actor: User | None = None,
    confirmed: bool = False,
) -> dict:
    """Autoriza a conexão para o sistema com o teto dado. A conexão nasce inativa."""
    _require_catalog(actor)
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        system = s.get(System, system_id)
        if conn is None or system is None:
            raise NotFound("conexão ou sistema não encontrado")
        _check_mode(max_mode, conn.kind)
        exists = s.execute(
            select(DbConnectionGrant.id).where(
                DbConnectionGrant.connection_id == connection_id, DbConnectionGrant.system_id == system_id
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise GrantExists(f"a conexão já está autorizada para o sistema {system.slug}")
        _confirm_schema_admin(s, connection_id, system_id, max_mode, confirmed)
        grant = DbConnectionGrant(
            connection_id=connection_id, system_id=system_id, max_mode=max_mode, active=False,
            mode=max_mode if max_mode != "schema_admin" else "read_write",
            granted_by_email=actor.email if actor else None,
        )
        s.add(grant)
        s.flush()
        grant_id, conn_name = grant.id, conn.name
    audit.record(
        **_actor_fields(actor), action="conn.grant", resource_type="connection", resource_id=connection_id,
        system_id=system_id, details={"name": conn_name, "max_mode": max_mode},
    )
    return {"grant_id": grant_id}


def _notice(s, system_id: str, kind: str, connection_name: str, alias: str | None, detail: str,
            actor: User | None) -> None:
    s.add(SystemConnectionNotice(
        system_id=system_id, kind=kind, connection_name=connection_name, alias=alias, detail=detail,
        actor_email=actor.email if actor else None,
    ))


def revoke_grant(grant_id: str, actor: User | None = None) -> dict:
    """Revoga na hora. Se estava ativa, o sistema é reprovisionado e o dono recebe um aviso.
    Devolve `{"rotate_key": bool}` (BigQuery que estava ativo)."""
    _require_catalog(actor)
    with session_scope() as s:
        grant = s.get(DbConnectionGrant, grant_id)
        if grant is None:
            raise NotFound("autorização não encontrada")
        conn = s.get(DbConnection, grant.connection_id)
        was_active, system_id, alias = grant.active, grant.system_id, grant.alias
        conn_id, conn_name, kind = conn.id, conn.name, conn.kind
        if was_active:
            _notice(s, system_id, "revoked", conn_name, alias,
                    "a autorização foi revogada e a conexão deixou de ser entregue ao sistema", actor)
        s.delete(grant)
    audit.record(
        **_actor_fields(actor), action="conn.revoke", resource_type="connection", resource_id=conn_id,
        system_id=system_id, details={"name": conn_name, "alias": alias, "was_active": was_active},
    )
    if was_active:
        _refresh_systems([system_id])
    return {"rotate_key": kind == "bigquery" and was_active}


def set_ceiling(grant_id: str, max_mode: str, actor: User | None = None, confirmed: bool = False) -> dict:
    """Altera o teto. Abaixo do modo vigente, o modo cai junto na hora (spec "Rebaixamento de
    teto com efeito imediato"); elevar não muda o modo vigente."""
    _require_catalog(actor)
    with session_scope() as s:
        grant = s.get(DbConnectionGrant, grant_id)
        if grant is None:
            raise NotFound("autorização não encontrada")
        conn = s.get(DbConnection, grant.connection_id)
        _check_mode(max_mode, conn.kind)
        _confirm_schema_admin(s, grant.connection_id, grant.system_id, max_mode, confirmed)
        old_ceiling, old_mode = grant.max_mode, grant.mode
        grant.max_mode = max_mode
        lowered = _MODE_RANK[grant.mode] > _MODE_RANK[max_mode]
        if lowered:
            grant.mode = max_mode
            if grant.mode != "schema_admin":
                grant.schema_admin_since = None
        effective = lowered and grant.active
        if effective:
            _notice(s, grant.system_id, "ceiling_lowered", conn.name, grant.alias,
                    f"o modo de acesso caiu de {MODE_LABELS[old_mode]} para {MODE_LABELS[max_mode]}", actor)
        system_id, conn_id, conn_name = grant.system_id, conn.id, conn.name
    audit.record(
        **_actor_fields(actor), action="conn.ceiling", resource_type="connection", resource_id=conn_id,
        system_id=system_id, details={"name": conn_name, "old": old_ceiling, "new": max_mode},
    )
    if effective:
        _refresh_systems([system_id])
    return {"mode_lowered": effective}


# --- Ativação (quem gerencia o sistema) -----------------------------------------------------

def list_system_connections(system_id: str) -> list[dict]:
    """Conexões autorizadas para o sistema, na projeção do dono."""
    with session_scope() as s:
        rows = s.execute(
            select(DbConnectionGrant, DbConnection)
            .join(DbConnection, DbConnection.id == DbConnectionGrant.connection_id)
            .where(DbConnectionGrant.system_id == system_id)
            .order_by(DbConnection.name)
        ).all()
        return [_owner_view(g, c) for g, c in rows]


def _load_grant(s, system: System, grant_id: str) -> tuple[DbConnectionGrant, DbConnection]:
    grant = s.get(DbConnectionGrant, grant_id)
    if grant is None or grant.system_id != system.id:
        raise NotFound("conexão não autorizada para este sistema")
    return grant, s.get(DbConnection, grant.connection_id)


def _apply_mode(grant: DbConnectionGrant, conn: DbConnection, mode: str) -> None:
    _check_mode(mode, conn.kind)
    if _MODE_RANK[mode] > _MODE_RANK[grant.max_mode]:
        raise InvalidMode(f"o modo {mode} está acima do teto da autorização ({grant.max_mode})")
    if mode == "schema_admin" and grant.schema_admin_since is None:
        grant.schema_admin_since = utcnow()
    elif mode != "schema_admin":
        grant.schema_admin_since = None
    grant.mode = mode


def activate(system: System, grant_id: str, alias: str, mode: str, actor: User | None = None) -> dict:
    _require_system_manager(actor, system)
    clean = _validate_alias(alias)
    key = env_key(clean)
    with session_scope() as s:
        grant, conn = _load_grant(s, system, grant_id)
        if grant.active:
            raise InvalidAlias("a conexão já está ativa; o alias não muda enquanto ela estiver ativa")
        clash = s.execute(
            select(DbConnectionGrant.id).where(
                DbConnectionGrant.system_id == system.id, DbConnectionGrant.active.is_(True),
                DbConnectionGrant.alias_key == key, DbConnectionGrant.id != grant_id,
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise AliasTaken(f"outra conexão ativa já usa o alias '{clean}' (ou gera a mesma variável)")
        _apply_mode(grant, conn, mode)
        grant.alias, grant.alias_key, grant.active = clean, key, True
        conn_id = conn.id
    audit.record(
        **_actor_fields(actor), action="conn.activate", resource_type="connection", resource_id=conn_id,
        system_id=system.id, details={"alias": clean, "mode": mode},
    )
    _refresh_systems([system.id])
    return {"alias": clean, "mode": mode}


def deactivate(system: System, grant_id: str, actor: User | None = None) -> None:
    _require_system_manager(actor, system)
    with session_scope() as s:
        grant, conn = _load_grant(s, system, grant_id)
        if not grant.active:
            return
        grant.active = False
        grant.schema_admin_since = None
        alias, conn_id = grant.alias, conn.id
    audit.record(
        **_actor_fields(actor), action="conn.deactivate", resource_type="connection", resource_id=conn_id,
        system_id=system.id, details={"alias": alias},
    )
    _refresh_systems([system.id])


def set_mode(system: System, grant_id: str, mode: str, actor: User | None = None) -> None:
    _require_system_manager(actor, system)
    with session_scope() as s:
        grant, conn = _load_grant(s, system, grant_id)
        if not grant.active:
            raise InvalidMode("ative a conexão antes de mudar o modo")
        old = grant.mode
        if old == mode:
            return
        _apply_mode(grant, conn, mode)
        alias, conn_id = grant.alias, conn.id
    audit.record(
        **_actor_fields(actor), action="conn.mode", resource_type="connection", resource_id=conn_id,
        system_id=system.id, details={"alias": alias, "old": old, "new": mode},
    )
    _refresh_systems([system.id])


def list_notices(system_id: str) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(SystemConnectionNotice)
            .where(SystemConnectionNotice.system_id == system_id, SystemConnectionNotice.dismissed_at.is_(None))
            .order_by(SystemConnectionNotice.created_at.desc())
        ).scalars().all()
        return [
            {"id": n.id, "kind": n.kind, "connection_name": n.connection_name, "alias": n.alias,
             "detail": n.detail, "actor_email": n.actor_email, "created_at": n.created_at.isoformat()}
            for n in rows
        ]


def dismiss_notice(system: System, notice_id: str, actor: User | None = None) -> None:
    _require_system_manager(actor, system)
    with session_scope() as s:
        notice = s.get(SystemConnectionNotice, notice_id)
        if notice is None or notice.system_id != system.id:
            raise NotFound("aviso não encontrado")
        notice.dismissed_at = utcnow()


# --- Conexões vigentes (design D6): o único leitor usado pelo provisionamento ----------------

@dataclass(frozen=True)
class ActiveConnection:
    """Uma conexão ativa num sistema: o que o provisionamento entrega ao agente e à app."""

    connection_id: str
    alias: str
    mode: str
    kind: str
    host: str
    port: int
    database: str
    username: str
    description: str | None

    @property
    def env_name(self) -> str:
        return env_key(self.alias)


def active_connections(system_id: str) -> list[ActiveConnection]:
    """Conexões ativas do sistema, na ordem em que foram autorizadas (estável entre chamadas)."""
    with session_scope() as s:
        rows = s.execute(
            select(DbConnectionGrant, DbConnection)
            .join(DbConnection, DbConnection.id == DbConnectionGrant.connection_id)
            .where(DbConnectionGrant.system_id == system_id, DbConnectionGrant.active.is_(True))
            .order_by(DbConnectionGrant.created_at, DbConnectionGrant.id)
        ).all()
        return [
            ActiveConnection(
                connection_id=c.id, alias=g.alias or c.name, mode=g.mode, kind=c.kind, host=c.host,
                port=c.port, database=c.database, username=c.username, description=c.description,
            )
            for g, c in rows
        ]


def _active_system_ids(connection_id: str) -> list[str]:
    with session_scope() as s:
        return list(s.execute(
            select(DbConnectionGrant.system_id).where(
                DbConnectionGrant.connection_id == connection_id, DbConnectionGrant.active.is_(True)
            )
        ).scalars())


# --- Saúde (design D11) ----------------------------------------------------------------------

def list_degraded_connections() -> list[dict]:
    """Conexões degradadas do catálogo, com os sistemas para os quais estão autorizadas."""
    with session_scope() as s:
        conns = s.execute(
            select(DbConnection).where(DbConnection.status == "degraded").order_by(DbConnection.name)
        ).scalars().all()
        views = [_catalog_view(c) for c in conns]
    for view in views:
        view["systems"] = connection_systems(view["id"])
    return views


def check_all_connections_health() -> None:
    """Uma checagem por conexão do catálogo, autorizada ou não; erros por conexão não param a passada."""
    with session_scope() as s:
        ids = list(s.execute(select(DbConnection.id)).scalars())
    for conn_id in ids:
        try:
            check_connection_health(conn_id)
        except Exception:  # noqa: BLE001
            log.exception("health check falhou para conexão %s", conn_id)


def check_connection_health(conn_id: str) -> None:
    """Testa a conexão com timeout de 2s e atualiza status; nunca levanta exceção."""
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


def get_connection_secret(connection_id: str) -> tuple[DbConnection, str]:
    """Uso interno do provisionamento (env do container); nunca expor à UI."""
    with session_scope() as s:
        conn = s.get(DbConnection, connection_id)
        assert conn is not None
        secret = decrypt_secret(conn.password_encrypted)
        s.expunge(conn)
        return conn, secret


# --- Reprovisionamento (design D7) -----------------------------------------------------------

def _refresh_systems(system_ids: list[str]) -> None:
    """Reaplica as conexões vigentes aos sistemas, em sequência, fora do request."""
    import threading

    from .systems import get_system

    systems = [sys_ for sys_ in (get_system(sid) for sid in dict.fromkeys(system_ids)) if sys_ is not None]
    if not systems:
        return

    def work() -> None:
        from ..provisioning import refresh_connections

        for system in systems:
            try:
                refresh_connections(system)
            except Exception:
                log.exception("não foi possível aplicar conexões ao container de %s", system.slug)

    name = f"refresh-conn-{systems[0].slug}" if len(systems) == 1 else f"refresh-conn-{len(systems)}-sistemas"
    threading.Thread(target=work, daemon=True, name=name).start()
