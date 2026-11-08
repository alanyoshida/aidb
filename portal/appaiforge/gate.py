"""Serviço do gate de operações destrutivas (spec destructive-gate).

Decide com o classificador canônico (sqlgate) e audita toda decisão:
- bloqueada  -> recusada automaticamente (decisão "bloqueada");
- normal     -> aprovada automaticamente;
- confirmável-> sem decisão automática (aguarda o editor no chat ou a
                confirmação na app); o registro acontece no momento da decisão.
"""

import enum
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .app_template import sqlgate
from .db import session_scope
from .models import AgentRun, GateDecision, GateRequest, RunStatus


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


# ---------- pedidos de aprovação do proxy de banco (task 4.1, change db-proxy-gate-data-plane) ----------
#
# O proxy roda num sidecar — container separado do portal — e não tem como
# chamar `agent_queue.decide_gate` em processo (esse caminho é só do
# protocolo de permissão do harness). Por isso a statement confirmável vira
# um pedido persistido aqui, que o proxy cria e consulta por HTTP (endpoints
# internos em `main.py`, autenticados por token de serviço — mesmo padrão do
# broker da etapa 3) enquanto segura a conexão. `decide_request` é chamada em
# processo pela UI de aprovação do chat (task 4.2) — não precisa de endpoint.

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _active_run_id(system_id: str, s) -> str | None:
    """Mesma atribuição do broker (`services.systems.inference_context`): a
    serialização de um run por sistema dá a atribuição de graça — não há
    como duas execuções do agente estarem com uma statement confirmável
    pendente ao mesmo tempo no mesmo sistema."""
    run = s.execute(
        select(AgentRun)
        .where(AgentRun.system_id == system_id, AgentRun.status.in_([RunStatus.running, RunStatus.awaiting_approval]))
        .order_by(AgentRun.created_at.desc())
    ).scalars().first()
    return run.id if run else None


class GateRequestStatus(str, enum.Enum):
    PENDING = "pendente"
    APPROVED = "aprovada"
    REJECTED = "recusada"
    EXPIRED = "expirada"


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
    enforce, classificação bloqueada) antes de chamar isto — decision vira
    "bloqueada", igual à auditoria imediata que o caminho antigo
    (`gate.evaluate`) sempre fez pra DDL. Sem isso, um `DROP TABLE`
    recusado em enforce não deixava rastro nenhum em `GateDecision`."""
    gate_class, _reason = classify_sql(sql)
    with session_scope() as s:
        run_id = _active_run_id(system_id, s) if origin == "agente" else None
    decision = "bloqueada" if enforced else "sombra"
    record_decision(
        system_id, sql, origin=origin, connection_name=connection_name,
        classification=gate_class, decision=decision, run_id=run_id,
    )
    if enforced and run_id:
        _notify_chat_blocked(run_id, sql)
    return gate_class


def _notify_chat_blocked(run_id: str, sql: str) -> None:
    """Pedido do operador (task 7.3, enforce): um bloqueio de DDL no proxy
    (data plane) não tinha nenhuma visibilidade no chat, só na auditoria
    silenciosa — diferente do confirmável em enforce, que já segura e mostra
    o card próprio de aprovação (task 4.2). Reaproveita o mesmo RunEvent
    `gate_denied` do caminho antigo (control plane) para o mesmo tratamento
    visual (card vermelho, ícone de bloqueio) e a query bloqueada à mostra.

    Melhor esforço: se a run já tiver terminado e o buffer já foi
    descartado, a auditoria em `GateDecision` continua sendo o registro
    (visível na aba Auditoria) — só a notificação ao vivo no chat se perde."""
    from .agent_queue import get_queue
    from .harness.base import RunEvent

    buffer = get_queue().buffers.get(run_id)
    if buffer is not None:
        buffer.push(RunEvent("gate_denied", text=f"bloqueada pelo proxy de banco: {sql}"))


def _serialize_request(row: GateRequest) -> dict:
    return {
        "id": row.id,
        "system_id": row.system_id,
        "run_id": row.run_id,
        "origin": row.origin,
        "sql": row.sql,
        "connection_name": row.connection_name,
        "reason": row.reason,
        "status": row.status,
        "author_id": row.author_id,
        "author_email": row.author_email,
        "created_at": row.created_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


def create_request(
    system_id: str,
    sql: str,
    *,
    origin: str,
    connection_name: str = "",
    reason: str = "",
    timeout_seconds: int | None = None,
) -> dict:
    """Registra o pedido pendente; o proxy segura a conexão e consulta
    `get_request` até sair de "pendente" (aprovada/recusada/expirada).

    O run/sessão associados são resolvidos aqui, não recebidos do chamador
    (task 4.2) — o proxy só sabe o `system_id`; confiar num `run_id` que ele
    mandasse abriria a porta para atribuir a decisão à run errada. Origem
    `app` nunca tem run (a app gerada não é uma execução do agente)."""
    from .config import get_settings

    if timeout_seconds is None:
        timeout_seconds = get_settings().db_gate_approval_timeout_seconds
    now = _utcnow()
    with session_scope() as s:
        run_id = _active_run_id(system_id, s) if origin == "agente" else None
        row = GateRequest(
            system_id=system_id,
            run_id=run_id,
            origin=origin,
            sql=sql,
            connection_name=connection_name,
            reason=reason,
            status=GateRequestStatus.PENDING.value,
            created_at=now,
            expires_at=now + timedelta(seconds=timeout_seconds),
        )
        s.add(row)
        s.flush()
        result = _serialize_request(row)
        s.expunge(row)
        return result


def _expire_if_due(row: GateRequest) -> dict | None:
    """Vira "expirada" se o prazo passou sem decisão — e, só na transição
    (não em releitura de um pedido já expirado), devolve os dados pra
    auditar em `GateDecision` fora da sessão de quem chamou. A auditoria de
    "expirada" tinha ficado de fora da primeira versão desta task: um
    pedido que estoura o prazo sem editor nenhum decidir não tinha nenhum
    registro na tabela de auditoria oficial, só no `GateRequest` em si."""
    if row.status == GateRequestStatus.PENDING.value and _utcnow() >= row.expires_at:
        row.status = GateRequestStatus.EXPIRED.value
        row.decided_at = _utcnow()
        return {
            "system_id": row.system_id, "sql": row.sql, "origin": row.origin,
            "connection_name": row.connection_name, "run_id": row.run_id,
        }
    return None


def _audit_expired(expired: dict | None) -> None:
    if expired is None:
        return
    record_decision(
        expired["system_id"], expired["sql"], origin=expired["origin"],
        connection_name=expired["connection_name"], classification=GateClass.CONFIRMABLE,
        decision="expirada", run_id=expired["run_id"],
    )


def get_request(request_id: str) -> dict | None:
    """Expira preguiçosamente: se o prazo passou sem decisão, vira "expirada"
    nesta própria consulta (sem job de fundo — o proxy já está poll-ando)."""
    with session_scope() as s:
        row = s.get(GateRequest, request_id)
        if row is None:
            return None
        expired = _expire_if_due(row)
        s.flush()
        result = _serialize_request(row)
        s.expunge(row)
    _audit_expired(expired)
    return result


def list_pending_for_run(run_id: str) -> list[dict]:
    """Pendências ativas de um run — a UI de aprovação do chat lista daqui
    (task 4.2). Mesma expiração preguiçosa do `get_request`: sem isso, uma
    statement expirada ficaria aparecendo como pendente pra sempre no chat
    até alguém chamar `get_request` por fora (só o proxy faz isso)."""
    with session_scope() as s:
        rows = s.execute(
            select(GateRequest).where(GateRequest.run_id == run_id, GateRequest.status == GateRequestStatus.PENDING.value)
        ).scalars().all()
        expired_list = [e for row in rows if (e := _expire_if_due(row)) is not None]
        s.flush()
        still_pending = [r for r in rows if r.status == GateRequestStatus.PENDING.value]
        still_pending.sort(key=lambda r: r.created_at)
        result = [_serialize_request(r) for r in still_pending]
        for r in rows:
            s.expunge(r)
    for expired in expired_list:
        _audit_expired(expired)
    return result


def decide_request(
    request_id: str, approve: bool, *, author_id: str | None = None, author_email: str = ""
) -> dict | None:
    """Decisão do editor. Idempotente: um pedido já decidido ou expirado
    devolve o estado existente sem sobrescrever. Também grava o `GateDecision`
    de auditoria, igual ao caminho do agente."""
    audit_args = None
    with session_scope() as s:
        row = s.get(GateRequest, request_id)
        if row is None:
            return None
        expired = _expire_if_due(row)
        if row.status == GateRequestStatus.PENDING.value:
            row.status = GateRequestStatus.APPROVED.value if approve else GateRequestStatus.REJECTED.value
            row.decided_at = _utcnow()
            row.author_id = author_id
            row.author_email = author_email or ""
            audit_args = (row.system_id, row.sql, row.origin, row.connection_name, row.run_id, approve)
        s.flush()
        result = _serialize_request(row)
        s.expunge(row)

    _audit_expired(expired)
    if audit_args is not None:
        system_id, sql, origin, connection_name, run_id, approved = audit_args
        record_decision(
            system_id, sql, origin=origin, connection_name=connection_name,
            classification=GateClass.CONFIRMABLE,
            decision="aprovada" if approved else "recusada",
            run_id=run_id, author_id=author_id, author_email=author_email,
        )
    return result
