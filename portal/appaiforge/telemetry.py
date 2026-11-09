"""Instrumentação OTel (change agent-telemetry-otel, capability agent-telemetry).

Sempre presente no código do portal e do broker, inerte quando nenhum
endpoint de exportação está configurado (comportamento padrão do SDK OTel
sem exporter) — nenhum `if` de aplicação liga ou desliga isto, só a
presença de `APPAIFORGE_OTEL_TRACES_ENDPOINT`/`APPAIFORGE_OTEL_LOGS_ENDPOINT`.

Portal e broker são processos separados e não compartilham memória: o
span raiz `agent.run` (criado só pelo portal, em `agent_queue.py`) e os
spans filhos emitidos por qualquer um dos dois processos (`db.query`,
`tool.*`, `policy.decision`, `llm.request`) ficam no mesmo trace porque o
trace_id e o span_id do span raiz são determinísticos a partir do
`run_id` — nenhuma chamada de rede nova só para telemetria é necessária
para o broker "descobrir" o contexto do span raiz.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

LOGGER_NAME = "appaiforge.telemetry"

_configured = False
_pending_root_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aidb_pending_root_run_id", default=None
)


def _hash_id(*parts: str, size: int) -> int:
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()
    value = int(digest[: size * 2], 16)
    return value or 1  # trace_id/span_id de valor 0 são inválidos no OTel


def run_trace_id(run_id: str) -> int:
    """trace_id (128 bits) determinístico a partir do `run_id`."""
    return _hash_id("aidb-run-trace", run_id, size=16)


def run_root_span_id(run_id: str) -> int:
    """span_id (64 bits) determinístico do span raiz `agent.run` dessa run."""
    return _hash_id("aidb-run-root-span", run_id, size=8)


class _DeterministicRootIdGenerator(IdGenerator):
    """IDs determinísticos só para o span raiz `agent.run` (via
    `start_run_root_span`); qualquer outro span usa IDs aleatórios normais."""

    def __init__(self) -> None:
        self._fallback = RandomIdGenerator()

    def generate_span_id(self) -> int:
        run_id = _pending_root_run_id.get()
        if run_id is not None:
            return run_root_span_id(run_id)
        return self._fallback.generate_span_id()

    def generate_trace_id(self) -> int:
        run_id = _pending_root_run_id.get()
        if run_id is not None:
            return run_trace_id(run_id)
        return self._fallback.generate_trace_id()


class _PostgresSpanExporter(SpanExporter):
    """Persiste spans finalizados em `agent_telemetry_spans`, pro Debug log
    do chat ler sem depender de nenhum backend de observabilidade externo
    (change agent-telemetry-backend-agnostic). Melhor esforço: uma falha ao
    gravar (ex.: Postgres indisponível, FK inexistente) nunca propaga pro
    chamador — devolve `FAILURE` e segue, sem travar `on_end()` nem a
    execução que criou o span. Usado dentro de um `BatchSpanProcessor`, que
    já enfileira sem bloquear; esta classe é defensiva por si só, e não só
    por depender desse processor."""

    def export(self, spans) -> SpanExportResult:
        from .db import session_scope
        from .models import AgentTelemetrySpan, new_id

        # Cada span é persistido na sua própria transação: um span órfão
        # (ex.: `run_id` sem `AgentRun` correspondente) só faz aquela
        # linha falhar, sem levar embora o resto do lote num rollback só.
        any_failure = False
        for span in spans:
            run_id = (span.attributes or {}).get("run_id")
            if not run_id:
                continue
            row = AgentTelemetrySpan(
                id=new_id(),
                run_id=run_id,
                span_id=f"{span.context.span_id:016x}",
                parent_span_id=f"{span.parent.span_id:016x}" if span.parent else None,
                name=span.name,
                start_time=datetime.fromtimestamp(span.start_time / 1e9, tz=timezone.utc),
                end_time=datetime.fromtimestamp(span.end_time / 1e9, tz=timezone.utc),
                attributes=dict(span.attributes or {}),
            )
            try:
                with session_scope() as s:
                    s.add(row)
            except Exception:  # noqa: BLE001 - melhor esforço: nunca propaga pro chamador
                any_failure = True
        return SpanExportResult.FAILURE if any_failure else SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def configure(service_name: str) -> None:
    """Liga a exportação de traços/logs; chamado uma vez na inicialização
    do portal e do broker. Idempotente (chamadas seguintes não fazem nada).

    O `TracerProvider` e a persistência de spans em Postgres (pro Debug log)
    ficam sempre ativos, independente de qualquer endpoint de exportação
    estar configurado; a exportação OTLP pro Collector é adicionada à parte,
    só quando `APPAIFORGE_OTEL_TRACES_ENDPOINT` estiver definida."""
    global _configured
    if _configured:
        return
    _configured = True

    from .config import get_settings

    settings = get_settings()
    resource = Resource.create({"service.name": service_name})

    provider = TracerProvider(resource=resource, id_generator=_DeterministicRootIdGenerator())
    provider.add_span_processor(BatchSpanProcessor(_PostgresSpanExporter()))
    if settings.otel_traces_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_traces_endpoint))
        )
    trace.set_tracer_provider(provider)

    if settings.otel_logs_endpoint:
        _configure_logs(resource, settings.otel_logs_endpoint)


def _configure_logs(resource: Resource, endpoint: str) -> None:
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint)))
    set_logger_provider(provider)
    handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("appaiforge")


def get_logger() -> logging.Logger:
    """Logger único para os eventos estruturados desta change (login,
    configuração de sistema, prompts, espelho da auditoria de gestão).
    Sem `configure()` chamado (ou sem endpoint de logs), é um logger
    Python comum — não lança nem silencia nada, só não é exportado."""
    return logging.getLogger(LOGGER_NAME)


def parent_context_for_run(run_id: str):
    """Contexto de propagação cujo span "pai" é o span raiz determinístico
    da run — usável em qualquer processo, sem depender de nenhum objeto em
    memória compartilhado."""
    span_context = trace.SpanContext(
        trace_id=run_trace_id(run_id),
        span_id=run_root_span_id(run_id),
        is_remote=True,
        trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED),
    )
    return trace.set_span_in_context(trace.NonRecordingSpan(span_context))


def start_run_root_span(run_id: str, attributes: dict) -> trace.Span:
    """Span raiz `agent.run`; o chamador guarda a referência e encerra com
    `.end()` quando a execução termina (sucesso, erro ou interrupção)."""
    token = _pending_root_run_id.set(run_id)
    try:
        return get_tracer().start_span("agent.run", attributes={"run_id": run_id, **attributes})
    finally:
        _pending_root_run_id.reset(token)


def start_child_span(run_id: str, name: str, attributes: dict | None = None) -> trace.Span:
    """Span filho do span raiz da run (`db.query`, `tool.*`,
    `policy.decision`, `llm.request`); o chamador encerra com `.end()`.
    `run_id` sempre vai pros atributos do span (não só pro contexto de
    propagação), pra o `_PostgresSpanExporter` conseguir persistir a linha
    sem depender de nenhum estado em memória compartilhado entre
    processos."""
    return get_tracer().start_span(
        name,
        context=parent_context_for_run(run_id),
        attributes={"run_id": run_id, **(attributes or {})},
    )


def cleanup_expired_spans() -> int:
    """Remove de `agent_telemetry_spans` os spans mais antigos que
    `APPAIFORGE_OTEL_SPAN_RETENTION_DAYS` (default 30). Best-effort - uma
    falha ao limpar (ex.: Postgres indisponível) não propaga; o próximo
    disparo do timer periódico tenta de novo. Retorna a quantidade
    removida, ou 0 em caso de falha."""
    from datetime import timedelta

    from sqlalchemy import delete

    from .config import get_settings
    from .db import session_scope
    from .models import AgentTelemetrySpan

    cutoff = datetime.now(timezone.utc) - timedelta(days=get_settings().otel_span_retention_days)
    try:
        with session_scope() as s:
            result = s.execute(delete(AgentTelemetrySpan).where(AgentTelemetrySpan.end_time < cutoff))
            return result.rowcount or 0
    except Exception:  # noqa: BLE001 - melhor esforço: a próxima execução do timer tenta de novo
        return 0


def start_span_cleanup_timer() -> None:
    """Registra `cleanup_expired_spans` como timer periódico de aplicação
    (não de página/cliente) - chamado uma única vez, no boot do portal
    (`main.create_app()`), ao lado de `reconcile_orphaned_runs()`.
    Intervalo em horas, não segundos: é limpeza periódica, não polling de UI."""
    from nicegui import app as nicegui_app

    nicegui_app.timer(6 * 3600, cleanup_expired_spans)
