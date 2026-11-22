"""Unitários da change portal-observability-otel (capability service-observability):
resource, sampler, sanitização, métricas e instrumentação de portal, broker,
banco e httpx."""

import http.server
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine, text

from appaiforge import __version__, telemetry


@pytest.fixture()
def provider():
    """TracerProvider próprio com o sampler da change e exporter em memória."""
    exporter = InMemorySpanExporter()
    tp = TracerProvider(sampler=telemetry.build_sampler())
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    tp.exporter = exporter
    return tp


# --- 2.1 resource -----------------------------------------------------------------

def test_resource_tem_nome_versao_e_instancia(monkeypatch):
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    attrs = telemetry.build_resource("appaiforge-portal").attributes
    assert attrs["service.name"] == "appaiforge-portal"
    assert attrs["service.version"] == __version__
    assert attrs["service.instance.id"]
    other = telemetry.build_resource("appaiforge-portal").attributes
    assert other["service.instance.id"] != attrs["service.instance.id"]


def test_otel_resource_attributes_prevalece_sobre_os_padroes(monkeypatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=producao,service.version=9.9.9")
    attrs = telemetry.build_resource("appaiforge-broker").attributes
    assert attrs["deployment.environment"] == "producao"
    assert attrs["service.version"] == "9.9.9"
    assert attrs["service.name"] == "appaiforge-broker"


# --- 2.2 sampler e span raiz ------------------------------------------------------

def test_span_client_sem_pai_nao_e_exportado(provider):
    tracer = provider.get_tracer("t")
    tracer.start_span("SELECT 1", kind=trace.SpanKind.CLIENT).end()
    assert provider.exporter.get_finished_spans() == ()


def test_span_client_filho_de_servidor_e_exportado(provider):
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("GET /x", kind=trace.SpanKind.SERVER):
        tracer.start_span("SELECT 1", kind=trace.SpanKind.CLIENT).end()
    names = {s.name for s in provider.exporter.get_finished_spans()}
    assert names == {"GET /x", "SELECT 1"}


def test_span_filho_de_pai_ja_encerrado_nao_e_exportado(provider):
    """Timer do NiceGUI criado na requisição da página: herda o contexto dela
    e roda depois de a transação terminar."""
    import asyncio

    from opentelemetry import context as otel_context

    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("GET /systems/{system_id}", kind=trace.SpanKind.SERVER):
        herdado = otel_context.get_current()
        tracer.start_span("SELECT durante", kind=trace.SpanKind.CLIENT).end()

    async def timer():
        tracer.start_span("SELECT depois", kind=trace.SpanKind.CLIENT).end()

    asyncio.run(_rodar_no_contexto(herdado, timer))
    names = {s.name for s in provider.exporter.get_finished_spans()}
    assert names == {"GET /systems/{system_id}", "SELECT durante"}


async def _rodar_no_contexto(ctx, coro_fn):
    from opentelemetry import context as otel_context

    token = otel_context.attach(ctx)
    try:
        await coro_fn()
    finally:
        otel_context.detach(token)


def test_filho_de_pai_remoto_continua_exportado(provider):
    ctx = telemetry.parent_context_for_run("run-remoto")
    provider.get_tracer("t").start_span("tool.bash", context=ctx).end()
    assert [s.name for s in provider.exporter.get_finished_spans()] == ["tool.bash"]


def test_agent_run_dentro_de_span_ativo_continua_raiz(finished_spans):
    with telemetry.get_tracer().start_as_current_span("GET /chat", kind=trace.SpanKind.SERVER):
        root = telemetry.start_run_root_span("run-raiz", {})
        root.end()
    run_span = next(s for s in finished_spans.get_finished_spans() if s.name == "agent.run")
    assert run_span.parent is None
    assert run_span.context.trace_id == telemetry.run_trace_id("run-raiz")
    assert run_span.context.span_id == telemetry.run_root_span_id("run-raiz")


# --- 2.3 sanitização --------------------------------------------------------------

def _span(attributes):
    context = trace.SpanContext(trace_id=1, span_id=2, is_remote=False, trace_flags=trace.TraceFlags(1))
    return ReadableSpan(name="GET /auth/callback", context=context, attributes=attributes,
                        kind=trace.SpanKind.SERVER, start_time=1, end_time=2)


def test_exporter_sanitizante_remove_query_string():
    inner = InMemorySpanExporter()
    exporter = telemetry.SanitizingSpanExporter(inner)
    exporter.export([_span({
        "url.full": "https://portal/auth/callback?code=abc&state=def",
        "url.query": "code=abc&state=def",
        "http.target": "/auth/callback?code=abc",
        "url.path": "/auth/callback",
        "http.response.status_code": 302,
    })])
    (span,) = inner.get_finished_spans()
    attrs = dict(span.attributes)
    assert "url.query" not in attrs
    assert attrs["url.full"] == "https://portal/auth/callback"
    assert attrs["http.target"] == "/auth/callback"
    assert attrs["url.path"] == "/auth/callback"
    assert attrs["http.response.status_code"] == 302
    assert "abc" not in json.dumps(attrs) and "def" not in json.dumps(attrs)
    assert span.name == "GET /auth/callback" and span.context.span_id == 2


def test_exporter_sanitizante_nao_mexe_em_span_sem_url():
    inner = InMemorySpanExporter()
    original = _span({"run_id": "r1"})
    telemetry.SanitizingSpanExporter(inner).export([original])
    assert inner.get_finished_spans()[0] is original


# --- 2.4 métricas -----------------------------------------------------------------

def _run_configure(monkeypatch, metrics_endpoint):
    from appaiforge.config import get_settings

    calls = []
    settings = get_settings().model_copy(update={
        "otel_metrics_endpoint": metrics_endpoint, "otel_traces_endpoint": "", "otel_logs_endpoint": "",
    })
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr("appaiforge.config.get_settings", lambda: settings)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda p: None)
    monkeypatch.setattr(telemetry, "_instrument_httpx", lambda: None)
    monkeypatch.setattr(telemetry, "_configure_metrics", lambda resource, endpoint: calls.append(endpoint))
    telemetry.configure("appaiforge-tests")
    return calls


def test_sem_endpoint_de_metricas_nao_configura_metricas(monkeypatch):
    assert _run_configure(monkeypatch, "") == []


def test_com_endpoint_de_metricas_configura_metricas(monkeypatch):
    assert _run_configure(monkeypatch, "http://otel-collector:4318/v1/metrics") == [
        "http://otel-collector:4318/v1/metrics"
    ]


def test_metricas_de_processo_chegam_ao_leitor(monkeypatch):
    from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor

    monkeypatch.setattr(telemetry.metrics, "set_meter_provider", lambda p: None)
    reader = InMemoryMetricReader()
    telemetry._configure_metrics(telemetry.build_resource("appaiforge-tests"), "http://x", reader=reader)
    try:
        data = reader.get_metrics_data()
        names = {
            metric.name
            for rm in data.resource_metrics
            for sm in rm.scope_metrics
            for metric in sm.metrics
        }
        assert "process.memory.usage" in names
        assert any(name.startswith("process.cpu") for name in names)
        assert data.resource_metrics[0].resource.attributes["service.name"] == "appaiforge-tests"
    finally:
        SystemMetricsInstrumentor().uninstrument()


# --- 3.1 requisições HTTP ---------------------------------------------------------

@pytest.fixture()
def instrumented_app(provider):
    app = FastAPI(telemetry=telemetry.fastapi_telemetry(tracer_provider=provider))

    @app.get("/api/itens/{item_id}")
    def item(item_id: str):
        return {"id": item_id}

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/_nicegui/2.0/static/app.js")
    def asset():
        return "x"

    return app


def _server_spans(provider):
    return [s for s in provider.exporter.get_finished_spans() if s.kind == trace.SpanKind.SERVER]


def test_rota_gera_span_de_servidor_com_metodo_rota_e_status(provider, instrumented_app):
    response = TestClient(instrumented_app).get("/api/itens/42?segredo=x")
    assert response.status_code == 200
    (span,) = _server_spans(provider)
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == "/api/itens/{item_id}"
    assert span.attributes["http.response.status_code"] == 200


def test_health_e_assets_do_nicegui_nao_geram_span(provider, instrumented_app):
    client = TestClient(instrumented_app)
    client.get("/api/health")
    client.get("/_nicegui/2.0/static/app.js")
    assert provider.exporter.get_finished_spans() == ()


def test_rota_nao_gera_spans_de_operacao(provider, instrumented_app):
    TestClient(instrumented_app).get("/api/itens/7")
    assert [s.kind for s in provider.exporter.get_finished_spans()] == [trace.SpanKind.SERVER]


def test_requisicao_com_traceparent_continua_o_traco(provider, instrumented_app):
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    parent_id = "00f067aa0ba902b7"
    TestClient(instrumented_app).get("/api/itens/1", headers={"traceparent": f"00-{trace_id}-{parent_id}-01"})
    (span,) = _server_spans(provider)
    assert span.context.trace_id == int(trace_id, 16)
    assert span.parent.span_id == int(parent_id, 16)


# --- 3.2 banco do portal ----------------------------------------------------------

def test_so_o_engine_instrumentado_gera_span_sem_valores(provider):
    portal_engine = create_engine("sqlite://")
    other_engine = create_engine("sqlite://")
    telemetry.instrument_engine(portal_engine, tracer_provider=provider)
    telemetry.instrument_engine(portal_engine, tracer_provider=provider)  # idempotente
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("GET /x", kind=trace.SpanKind.SERVER):
        with portal_engine.connect() as conn:
            conn.execute(text("SELECT :valor"), {"valor": "cpf-123"})
        with other_engine.connect() as conn:
            conn.execute(text("SELECT :valor"), {"valor": "cpf-456"})
    db_spans = [s for s in provider.exporter.get_finished_spans() if s.kind == trace.SpanKind.CLIENT]
    assert len(db_spans) == 1
    dumped = json.dumps(dict(db_spans[0].attributes))
    assert "SELECT" in dumped
    assert "cpf-123" not in dumped and "cpf-456" not in dumped


# --- 3.3 chamada do broker ao LiteLLM ---------------------------------------------

@pytest.fixture()
def upstream():
    """LiteLLM falso: servidor HTTP real (a instrumentação httpx envolve o
    transporte HTTP de verdade, não um MockTransport)."""
    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received["traceparent"] = self.headers.get("traceparent")
            self.rfile.read(int(self.headers.get("content-length") or 0))
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", received
    server.shutdown()


def test_chamada_ao_litellm_e_filha_de_llm_request(monkeypatch, finished_spans, upstream):
    from appaiforge import broker_app
    from appaiforge.config import get_settings

    base_url, received = upstream
    settings = get_settings().model_copy(update={
        "litellm_base_url": base_url, "inference_broker_allowed_hosts": "127.0.0.1",
    })
    monkeypatch.setattr(broker_app, "get_settings", lambda: settings)
    monkeypatch.setattr(broker_app, "system_id_from_token", lambda token: "sys-1")
    monkeypatch.setattr(broker_app, "validate_token", lambda token, version: "sys-1")

    async def fake_context(system_id):
        return {"run_id": "run-llm", "version": 1}

    monkeypatch.setattr(broker_app, "resolve_context", fake_context)

    response = TestClient(broker_app.app).post(
        "/v1/chat/completions", headers={"authorization": "Bearer aidb_x"}, json={"model": "m"}
    )
    assert response.status_code == 200

    spans = finished_spans.get_finished_spans()
    llm = next(s for s in spans if s.name == "llm.request")
    client = next(s for s in spans if s.kind == trace.SpanKind.CLIENT and s.parent
                  and s.parent.span_id == llm.context.span_id)
    run_trace = telemetry.run_trace_id("run-llm")
    assert llm.context.trace_id == run_trace
    assert client.context.trace_id == run_trace
    assert received["traceparent"] and f"{run_trace:032x}" in received["traceparent"]


def test_requisicao_gera_metrica_de_duracao_http(provider):
    from opentelemetry.sdk.metrics import MeterProvider

    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    app = FastAPI(telemetry=telemetry.fastapi_telemetry(tracer_provider=provider, meter_provider=meter_provider))

    @app.get("/api/ping")
    def ping():
        return "pong"

    TestClient(app).get("/api/ping")
    names = {
        metric.name
        for rm in reader.get_metrics_data().resource_metrics
        for sm in rm.scope_metrics
        for metric in sm.metrics
    }
    assert "http.server.request.duration" in names
