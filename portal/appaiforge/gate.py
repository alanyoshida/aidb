"""Serviço do gate de operações destrutivas (spec destructive-gate).

Decide com o classificador canônico (sqlgate) e audita toda decisão:
- bloqueada  -> recusada automaticamente (decisão "bloqueada");
- normal     -> aprovada automaticamente;
- confirmável-> sem decisão automática (aguarda o editor no chat ou a
                confirmação na app); o registro acontece no momento da decisão.
"""

import enum

from sqlalchemy import select

from .app_template import sqlgate
from .db import session_scope
from .models import GateDecision


class GateClass(str, enum.Enum):
    NORMAL = "normal"
    CONFIRMABLE = "confirmavel"
    BLOCKED = "bloqueada"


def classify_sql(sql: str) -> tuple[GateClass, str]:
    """(classe, motivo) — motivo preenchido para confirmável/bloqueada."""
    result = sqlgate.classify(sql)
    if isinstance(result, sqlgate.Blocked):
        return GateClass.BLOCKED, result.reason
    if isinstance(result, sqlgate.Confirmable):
        return GateClass.CONFIRMABLE, result.reason
    return GateClass.NORMAL, ""


def evaluate(
    system_id: str,
    sql: str,
    *,
    origin: str,
    connection_name: str = "",
    run_id: str | None = None,
    author_id: str | None = None,
    author_email: str | None = None,
) -> GateClass:
    """Avalia a statement: bloqueada e normais são decididas e auditadas aqui;
    confirmáveis retornam CONFIRMABLE sem registro (quem confirma registra depois
    via `record_decision`)."""
    gate_class, _reason = classify_sql(sql)
    if gate_class is GateClass.BLOCKED:
        record_decision(system_id, sql, origin=origin, connection_name=connection_name,
                        classification=gate_class, decision="bloqueada", run_id=run_id,
                        author_id=author_id, author_email=author_email)
    elif gate_class is GateClass.NORMAL:
        record_decision(system_id, sql, origin=origin, connection_name=connection_name,
                        classification=gate_class, decision="aprovada", run_id=run_id,
                        author_id=author_id, author_email=author_email)
    return gate_class


def record_decision(
    system_id: str,
    sql: str,
    *,
    origin: str,
    connection_name: str,
    classification: GateClass,
    decision: str,
    run_id: str | None = None,
    author_id: str | None = None,
    author_email: str | None = None,
) -> GateDecision:
    with session_scope() as s:
        row = GateDecision(
            system_id=system_id,
            run_id=run_id,
            origin=origin,
            sql=sql,
            connection_name=connection_name,
            classification=classification.value,
            decision=decision,
            author_id=author_id,
            author_email=author_email or "",
        )
        s.add(row)
        s.flush()
        s.expunge(row)
        return row


def extract_sql(command: str) -> str | None:
    """Extrai o SQL embutido num comando de bash (ex.: `psql ... -c "DELETE ..."`).

    Devolve None quando o comando não contém nenhuma statement identificável —
    o chamador decide o fallback (o gate trata como confirmável).
    """
    import re

    for segment in re.findall(r'"([^"]*)"|\'([^\']*)\'', command):
        text = segment[0] or segment[1]
        if re.search(r"\b(DELETE|UPDATE|DROP|TRUNCATE|ALTER|INSERT|SELECT|CREATE)\b", text, re.I):
            return text
    if re.search(r"\b(DELETE|UPDATE|DROP|TRUNCATE|ALTER|INSERT)\b", command, re.I):
        return command
    return None


def list_decisions(system_id: str, limit: int = 50) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(GateDecision)
            .where(GateDecision.system_id == system_id)
            .order_by(GateDecision.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "origin": r.origin,
                "sql": r.sql,
                "connection_name": r.connection_name,
                "classification": r.classification,
                "decision": r.decision,
                "author_id": r.author_id,
                "author_email": r.author_email,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
