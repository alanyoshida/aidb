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

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
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


def configure(service_name: str) -> None:
    """Liga a exportação de traços/logs quando os endpoints estiverem
    configurados; chamado uma vez na inicialização do portal e do broker.
    Idempotente (chamadas seguintes não fazem nada)."""
    global _configured
    if _configured:
        return
    _configured = True

    from .config import get_settings

    settings = get_settings()
    resource = Resource.create({"service.name": service_name})

    if settings.otel_traces_endpoint:
        provider = TracerProvider(resource=resource, id_generator=_DeterministicRootIdGenerator())
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
        return get_tracer().start_span("agent.run", attributes=attributes)
    finally:
        _pending_root_run_id.reset(token)


def start_child_span(run_id: str, name: str, attributes: dict | None = None) -> trace.Span:
    """Span filho do span raiz da run (`db.query`, `tool.*`,
    `policy.decision`, `llm.request`); o chamador encerra com `.end()`."""
    return get_tracer().start_span(name, context=parent_context_for_run(run_id), attributes=attributes or {})
