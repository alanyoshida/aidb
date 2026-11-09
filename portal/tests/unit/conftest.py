"""Conftest dos unitários: `trace.set_tracer_provider` só pode ser chamado
uma vez por processo, e `telemetry.configure()` já é chamado no import de
`broker_app.py` (change agent-telemetry-backend-agnostic torna o
TracerProvider sempre ativo, não só quando há endpoint de exportação) — então
em vez de instalar um provider próprio, este fixture acopla um
`InMemorySpanExporter` ao provider real que `configure()` já deixou
instalado, pra inspeção nos testes."""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from appaiforge import telemetry


@pytest.fixture(scope="session")
def otel_span_exporter():
    telemetry.configure("appaiforge-tests")
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider), (
        "esperava o TracerProvider real instalado por telemetry.configure()"
    )
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter


@pytest.fixture()
def finished_spans(otel_span_exporter):
    otel_span_exporter.clear()
    yield otel_span_exporter
    otel_span_exporter.clear()


@pytest.fixture()
def editor(clean_db):
    from appaiforge import auth
    from appaiforge.models import UserType

    return auth.create_user("telemetry@t.local", "pw", UserType.editor.value)
