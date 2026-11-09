"""Consulta a `agent_telemetry_spans` para o Debug log do chat (capability
agent-telemetry, requisito "Debug log do chat reflete o rastreamento quando
disponível").

Change agent-telemetry-backend-agnostic: deixou de consultar a API REST do
Tempo (acoplada a um backend específico) e passou a ler direto da tabela
Postgres que `telemetry._PostgresSpanExporter` já mantém, independente de
qualquer backend de observabilidade externo estar configurado. Sem nenhum
span persistido para a run, `fetch_run_trace` devolve `None` — o chamador
cai no comportamento atual (eventos em memória), sem nenhuma regressão."""

from __future__ import annotations


def fetch_run_trace(run_id: str) -> list[dict] | None:
    """Spans da execução `run_id`, do mais antigo para o mais novo, ou
    `None` se não houver nenhum span persistido para essa run, ou a
    consulta falhar (melhor esforço — nunca propaga erro)."""
    try:
        from sqlalchemy import select

        from ..db import session_scope
        from ..models import AgentTelemetrySpan

        with session_scope() as s:
            rows = s.execute(
                select(AgentTelemetrySpan)
                .where(AgentTelemetrySpan.run_id == run_id)
                .order_by(AgentTelemetrySpan.start_time)
            ).scalars().all()
            if not rows:
                return None
            return [
                {
                    "name": row.name,
                    "span_id": row.span_id,
                    "parent_span_id": row.parent_span_id,
                    "start_time_unix_nano": int(row.start_time.timestamp() * 1_000_000_000),
                    "end_time_unix_nano": int(row.end_time.timestamp() * 1_000_000_000),
                    "attributes": dict(row.attributes or {}),
                }
                for row in rows
            ]
    except Exception:  # noqa: BLE001 - melhor esforço: Postgres fora do ar não derruba o Debug log
        return None
