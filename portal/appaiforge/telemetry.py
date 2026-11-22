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
import os
import uuid
from datetime import datetime, timezone

from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator
from opentelemetry.sdk.trace.sampling import Decision, ParentBased, Sampler, SamplingResult
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


# Requisições que não viram span (change portal-observability-otel, design D1):
# health checks, assets e websocket do NiceGUI e o favicon.
_EXCLUDED_PATHS = ("/api/health", "/health", "/favicon.ico")
_EXCLUDED_PREFIXES = ("/_nicegui",)

# Atributos que levam a query string (design D3): `url.query` some; os demais
# perdem tudo a partir de `?` ou `#`.
_QUERY_ATTRIBUTES = ("url.query",)
_URL_ATTRIBUTES = ("url.full", "http.url", "http.target")

# Métricas de processo coletadas quando há endpoint de métricas (design D4).
_PROCESS_METRICS = {
    "process.cpu.time": ["user", "system"],
    "process.cpu.utilization": ["user", "system"],
    "process.memory.usage": None,
    "process.memory.virtual": None,
    "process.thread.count": None,
    "process.open_file_descriptor.count": None,
    "process.context_switches": ["involuntary", "voluntary"],
}


def _semconv_opt_in() -> None:
    """Convenções HTTP estáveis (`url.path`, `url.query`, `http.request.method`)
    em todas as instrumentações; o operador ainda pode trocar pela variável."""
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")


def build_resource(service_name: str) -> Resource:
    """Resource comum a traços, métricas e logs (design D5): nome, versão e
    instância vêm do código; `OTEL_RESOURCE_ATTRIBUTES`/`OTEL_SERVICE_NAME`
    prevalecem sobre eles (ex.: `deployment.environment`, `service.version`)."""
    from . import __version__

    defaults = Resource.create(
        {
            "service.name": service_name,
            "service.version": __version__,
            "service.instance.id": str(uuid.uuid4()),
        }
    )
    return defaults.merge(OTELResourceDetector().detect())


class _DropRootClientSampler(Sampler):
    """Descarta span raiz de kind CLIENT (design D2): consulta ou chamada HTTP
    feita sem nenhuma operação em curso (timers, reconciliação, handlers do
    websocket da UI) não vira um traço de um span só. Spans de servidor e o
    `agent.run` (INTERNAL) continuam."""

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None, trace_state=None):
        if kind == trace.SpanKind.CLIENT:
            return SamplingResult(Decision.DROP)
        return SamplingResult(Decision.RECORD_AND_SAMPLE, attributes)

    def get_description(self) -> str:
        return "DropRootClientSampler"


class _AidbSampler(Sampler):
    """`ParentBased` com `_DropRootClientSampler` para raízes, mais uma regra:
    span cujo pai local já terminou não é amostrado (design D2). Os timers
    que o NiceGUI cria ao montar uma página são tarefas asyncio que copiam o
    contexto da requisição; sem esta regra, cada consulta periódica deles
    vira filha da transação da página muito depois de ela ter terminado
    (achado ao vivo: 922 consultas penduradas num único `GET /systems/{id}`).
    Pai remoto (`traceparent`, `parent_context_for_run`) não tem fim
    conhecido e segue a regra normal."""

    def __init__(self) -> None:
        self._delegate = ParentBased(root=_DropRootClientSampler())

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None, trace_state=None):
        parent = trace.get_current_span(parent_context)
        if getattr(parent, "end_time", None) is not None:
            return SamplingResult(Decision.DROP)
        return self._delegate.should_sample(
            parent_context, trace_id, name, kind=kind, attributes=attributes, links=links, trace_state=trace_state
        )

    def get_description(self) -> str:
        return "AidbSampler"


def build_sampler() -> Sampler:
    return _AidbSampler()


def _strip_query(value):
    if not isinstance(value, str):
        return value
    return value.split("?", 1)[0].split("#", 1)[0]


def _sanitize_span(span: ReadableSpan) -> ReadableSpan:
    attributes = span.attributes or {}
    if not any(key in attributes for key in (*_QUERY_ATTRIBUTES, *_URL_ATTRIBUTES)):
        return span
    clean = {
        key: (_strip_query(value) if key in _URL_ATTRIBUTES else value)
        for key, value in attributes.items()
        if key not in _QUERY_ATTRIBUTES
    }
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=clean,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class SanitizingSpanExporter(SpanExporter):
    """Envolve o exporter OTLP e tira a query string dos spans antes de saírem
    do processo (design D3) — o `code`/`state` do retorno OIDC, por exemplo,
    nunca chega ao Collector. O exporter Postgres não precisa disto: só grava
    spans com `run_id`, e os automáticos não têm."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans) -> SpanExportResult:
        return self._inner.export([_sanitize_span(span) for span in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


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
    _semconv_opt_in()
    resource = build_resource(service_name)

    provider = TracerProvider(
        resource=resource, id_generator=_DeterministicRootIdGenerator(), sampler=build_sampler()
    )
    provider.add_span_processor(BatchSpanProcessor(_PostgresSpanExporter()))
    if settings.otel_traces_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(SanitizingSpanExporter(OTLPSpanExporter(endpoint=settings.otel_traces_endpoint)))
        )
    trace.set_tracer_provider(provider)

    if settings.otel_metrics_endpoint:
        _configure_metrics(resource, settings.otel_metrics_endpoint)

    if settings.otel_logs_endpoint:
        _configure_logs(resource, settings.otel_logs_endpoint)

    _instrument_httpx()


def _configure_metrics(resource: Resource, endpoint: str, reader=None) -> None:
    """`MeterProvider` com exportação OTLP periódica (design D4), cumulativo
    como o padrão do SDK — a conversão para delta, quando o backend pede, é
    do Collector. `reader` existe só para os testes injetarem um leitor em
    memória."""
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    if reader is None:
        reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    SystemMetricsInstrumentor(config=_PROCESS_METRICS).instrument(meter_provider=provider)


def _instrument_httpx() -> None:
    """Chamadas httpx de saída viram spans de cliente filhos da operação em
    curso e propagam `traceparent` (design D1)."""
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    instrumentor = HTTPXClientInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument()


def _excluded_request(scope) -> bool:
    path = scope.get("path", "")
    return path in _EXCLUDED_PATHS or path.startswith(_EXCLUDED_PREFIXES)


def fastapi_telemetry(**overrides) -> dict:
    """Configuração da telemetria nativa do FastAPI (`FastAPI(telemetry=...)`,
    design D1): span de servidor por requisição, continuando o `traceparent`
    recebido e nomeado pela rota (inclusive as páginas do NiceGUI montado),
    sem os caminhos de `_excluded_request`. A exclusão no app de fora também
    cala o app do NiceGUI montado por dentro. Desligados: `operation_spans`
    (spans de dependência e serialização, ruído) e `logs` (falhas de
    validação com os valores de entrada, risco de dado pessoal)."""
    return {"exclude": _excluded_request, "operation_spans": False, "logs": False, **overrides}


def instrument_engine(engine, *, tracer_provider=None, meter_provider=None):
    """Instrumenta só o engine dado (design D1) — nunca o `create_engine`
    global, que o `SQLAlchemyInstrumentor().instrument()` envolve mesmo
    recebendo um engine. Assim nenhum engine futuro de conexão de usuário
    entra nos traços por acidente. Devolve o `EngineTracer`."""
    from opentelemetry.instrumentation.sqlalchemy.engine import EngineTracer
    from opentelemetry.instrumentation.sqlalchemy.version import __version__ as instrumentation_version

    if getattr(engine, "_aidb_otel_tracer", None) is not None:
        return engine._aidb_otel_tracer  # create_app() chamado de novo: não duplicar listeners
    _semconv_opt_in()
    scope = "opentelemetry.instrumentation.sqlalchemy"
    tracer = trace.get_tracer(scope, instrumentation_version, tracer_provider)
    meter = metrics.get_meter(scope, instrumentation_version, meter_provider)
    connections_usage = meter.create_up_down_counter(
        name="db.client.connections.usage",
        unit="connections",
        description="The number of connections that are currently in state described by the state attribute.",
    )
    engine_tracer = EngineTracer(tracer, engine, connections_usage)
    engine._aidb_otel_tracer = engine_tracer
    return engine_tracer


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
        # Contexto vazio explícito (design D2): o span raiz não pode herdar um
        # span corrente (ex.: thread que herda contexto no Python 3.14
        # free-threaded), senão perde o trace_id determinístico que o broker
        # usa para se ligar a ele.
        return get_tracer().start_span(
            "agent.run", context=Context(), attributes={"run_id": run_id, **attributes}
        )
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
