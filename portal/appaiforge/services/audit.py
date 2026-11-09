"""Auditoria de gestão do portal (capability management-audit).

Registra toda ação de escrita da gestão (criar/editar/remover recursos do
portal) com autor, ação, recurso, alvo, sistema e data. É separada do gate de
SQL (`gate_decisions`). Segredos nunca são gravados: chaves de `details` com
nome sugestivo são descartadas.
"""

from sqlalchemy import select

from .. import telemetry
from ..db import session_scope
from ..models import ManagementAudit

_SECRET_MARKERS = ("senha", "password", "secret", "token", "api_key", "apikey", "chave", "key")
_log = telemetry.get_logger()


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _sanitize(details: dict | None) -> dict:
    return {k: v for k, v in (details or {}).items() if not _is_secret_key(k)}


def record(
    *,
    actor_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    system_id: str | None = None,
    details: dict | None = None,
    actor_email: str | None = None,
) -> ManagementAudit:
    """Grava uma entrada de auditoria; descarta qualquer campo de segredo."""
    sanitized = _sanitize(details)
    with session_scope() as s:
        row = ManagementAudit(
            actor_id=actor_id,
            actor_email=actor_email or "",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            system_id=system_id,
            details=sanitized,
        )
        s.add(row)
        s.flush()
        s.expunge(row)
    # Espelho em log centralizado (capability agent-telemetry) — mesmo
    # conteúdo sanitizado já gravado em ManagementAudit; não substitui nem
    # altera o registro em Postgres, que continua a fonte de verdade.
    _log.info(
        "ação administrativa registrada",
        extra={
            "actor_id": actor_id,
            "actor_email": actor_email or "",
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "system_id": system_id,
            "details": sanitized,
        },
    )
    return row


def _to_dict(row: ManagementAudit) -> dict:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "actor_email": row.actor_email,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "system_id": row.system_id,
        "details": row.details,
        "created_at": row.created_at.isoformat(),
    }


def list_global(
    limit: int = 100,
    *,
    actor_email: str | None = None,
    resource_type: str | None = None,
    action: str | None = None,
) -> list[dict]:
    with session_scope() as s:
        stmt = (
            select(ManagementAudit)
            .order_by(ManagementAudit.created_at.desc())
            .limit(limit)
        )
        if resource_type:
            stmt = stmt.where(ManagementAudit.resource_type == resource_type)
        if action:
            stmt = stmt.where(ManagementAudit.action == action)
        if actor_email:
            stmt = stmt.where(ManagementAudit.actor_email == actor_email)
        rows = s.execute(stmt).scalars().all()
        return [_to_dict(row) for row in rows]


def list_by_system(system_id: str, limit: int = 50) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(ManagementAudit)
            .where(ManagementAudit.system_id == system_id)
            .order_by(ManagementAudit.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [_to_dict(row) for row in rows]