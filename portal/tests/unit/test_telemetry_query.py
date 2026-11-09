"""Unitários de `services/telemetry_query.py` (task 6.1/6.2): sem
`APPAIFORGE_OTEL_TRACES_QUERY_URL` configurada, sempre `None` (o Debug log
cai no comportamento atual); configurada, consulta o Tempo e devolve a
árvore de spans ordenada, ou `None` em qualquer falha (melhor esforço)."""

import httpx
import pytest

from appaiforge.services import telemetry_query


@pytest.fixture()
def tempo_url(monkeypatch):
    monkeypatch.setenv("APPAIFORGE_OTEL_TRACES_QUERY_URL", "http://tempo:3200")
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield "http://tempo:3200"
    get_settings.cache_clear()


def test_sem_endpoint_configurado_nunca_consulta_nada(monkeypatch):
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    assert telemetry_query.fetch_run_trace("run-1") is None
    get_settings.cache_clear()


_TRACE_PAYLOAD = {
    "batches": [
        {
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "name": "agent.run",
                            "spanId": "root1",
                            "parentSpanId": "",
                            "startTimeUnixNano": "1000000000",
                            "endTimeUnixNano": "5000000000",
                            "attributes": [{"key": "run_id", "value": {"stringValue": "run-1"}}],
                        },
                        {
                            "name": "db.query",
                            "spanId": "child1",
                            "parentSpanId": "root1",
                            "startTimeUnixNano": "2000000000",
                            "endTimeUnixNano": "2500000000",
                            "attributes": [{"key": "classification", "value": {"stringValue": "normal"}}],
                        },
                    ]
                }
            ]
        }
    ]
}


def _mock_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/search":
        return httpx.Response(200, json={"traces": [{"traceID": "abc123"}]})
    if request.url.path == "/api/traces/abc123":
        return httpx.Response(200, json=_TRACE_PAYLOAD)
    return httpx.Response(404)


def test_consulta_o_tempo_e_devolve_a_arvore_de_spans_ordenada(tempo_url, monkeypatch):
    real_client_cls = httpx.Client
    monkeypatch.setattr(
        telemetry_query.httpx, "Client",
        lambda timeout=None: real_client_cls(transport=httpx.MockTransport(_mock_handler)),
    )

    spans = telemetry_query.fetch_run_trace("run-1")

    assert spans is not None
    assert [s["name"] for s in spans] == ["agent.run", "db.query"]
    assert spans[1]["parent_span_id"] == "root1"
    assert spans[1]["attributes"]["classification"] == "normal"


def test_trace_nao_encontrado_devolve_none(tempo_url, monkeypatch):
    real_client_cls = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"traces": []})

    monkeypatch.setattr(
        telemetry_query.httpx, "Client",
        lambda timeout=None: real_client_cls(transport=httpx.MockTransport(handler)),
    )

    assert telemetry_query.fetch_run_trace("run-sem-trace") is None


def test_falha_de_rede_devolve_none_sem_propagar_erro(tempo_url, monkeypatch):
    real_client_cls = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("tempo fora do ar")

    monkeypatch.setattr(
        telemetry_query.httpx, "Client",
        lambda timeout=None: real_client_cls(transport=httpx.MockTransport(handler)),
    )

    assert telemetry_query.fetch_run_trace("run-1") is None
