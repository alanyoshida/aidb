"""Conftest dos unitários: TracerProvider único em memória para os testes de
telemetria (change agent-telemetry-otel) — `trace.set_tracer_provider` só
pode ser chamado uma vez por processo, então toda a sessão de testes
compartilha o mesmo provider/exporter."""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from appaiforge.telemetry import _DeterministicRootIdGenerator


@pytest.fixture(scope="session")
def otel_span_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(id_generator=_DeterministicRootIdGenerator())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    assert isinstance(trace.get_tracer_provider(), TracerProvider), (
        "outro teste já instalou um TracerProvider global incompatível antes deste"
    )
    yield exporter


@pytest.fixture()
def finished_spans(otel_span_exporter):
    otel_span_exporter.clear()
    yield otel_span_exporter
    otel_span_exporter.clear()
