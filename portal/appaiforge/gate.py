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
from .models import AgentRun, GateDecision, RunStatus


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


# ---------- auditoria do proxy de banco (task 4.1, change db-proxy-gate-data-plane) ----------
#
# O proxy roda num sidecar — container separado do portal. `bloqueada` e
# `confirmável` em modo enforce nunca chegam ao upstream: o proxy recusa a
# conexão na hora, por conta própria, sem pedir decisão a um humano (uma
# DELETE/UPDATE sem WHERE restritivo é tratada como destrutiva igual a um
# DDL — decisão do operador, não uma lacuna). O papel deste módulo é só
# registrar essa recusa em `GateDecision` (endpoint interno em `main.py`,
# autenticado por token de serviço) e avisar o chat quando há uma run ativa.

def _active_run_id(system_id: str, s) -> str | None:
    """Mesma atribuição do broker (`services.systems.inference_context`): a
    serialização de um run por sistema dá a atribuição de graça."""
    run = s.execute(
        select(AgentRun)
        .where(AgentRun.system_id == system_id, AgentRun.status.in_([RunStatus.running, RunStatus.awaiting_approval]))
        .order_by(AgentRun.created_at.desc())
    ).scalars().first()
    return run.id if run else None


def record_shadow_decision(
    system_id: str, sql: str, *, origin: str, connection_name: str = "", enforced: bool = False
) -> GateClass:
    """Audita uma statement que o proxy classificou, sem pendência humana
    (task 6.1; `enforced` fecha uma lacuna achada no roteiro de teste
    manual da change). Reclassifica aqui em vez de confiar na classificação
    que o proxy mandasse: o classificador canônico é a única fonte de
    verdade.

    `enforced=False` (default, modo sombra): decision="sombra" — nada foi
    de fato aplicado, só observado (comparação do spike S5, task 6.2).
    `enforced=True`: o proxy JÁ recusou a statement de verdade (modo
    enforce — bloqueada OU confirmável, as duas são recusadas na hora, sem
    segurar a conexão) antes de chamar isto — decision vira "bloqueada".
    Sem isso, uma statement recusada em enforce não deixava rastro nenhum
    em `GateDecision`."""
    gate_class, reason = classify_sql(sql)
    with session_scope() as s:
        run_id = _active_run_id(system_id, s) if origin == "agente" else None
    decision = "bloqueada" if enforced else "sombra"
    record_decision(
        system_id, sql, origin=origin, connection_name=connection_name,
        classification=gate_class, decision=decision, run_id=run_id,
    )
    if run_id:
        from . import telemetry

        span = telemetry.start_child_span(
            run_id, "db.query",
            attributes={
                "system_id": system_id,
                "connection_name": connection_name,
                "classification": gate_class.value,
                "decision": decision,
            },
        )
        span.end()
    if enforced and run_id:
        _notify_chat_blocked(run_id, sql, reason)
    return gate_class


def _notify_chat_blocked(run_id: str, sql: str, reason: str = "") -> None:
    """Pedido do operador (task 7.3, enforce): um bloqueio no proxy (data
    plane) não tinha nenhuma visibilidade no chat, só na auditoria
    silenciosa. Reaproveita o mesmo RunEvent `gate_denied` do caminho antigo
    (control plane) para o mesmo tratamento visual (card vermelho, ícone de
    bloqueio), a query bloqueada à mostra e o motivo (DDL vs. DELETE/UPDATE
    sem WHERE restritivo) — as duas classes são recusadas do mesmo jeito em
    enforce, sem pedir aprovação a ninguém.

    Melhor esforço: se a run já tiver terminado e o buffer já foi
    descartado, a auditoria em `GateDecision` continua sendo o registro
    (visível na aba Auditoria) — só a notificação ao vivo no chat se perde."""
    from .agent_queue import get_queue
    from .harness.base import RunEvent

    buffer = get_queue().buffers.get(run_id)
    if buffer is not None:
        text = f"bloqueada pelo proxy de banco: {sql}"
        if reason:
            text += f" ({reason})"
        buffer.push(RunEvent("gate_denied", text=text))
