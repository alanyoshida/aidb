"""Consulta ao Tempo para o Debug log do chat (capability agent-telemetry,
requisito "Debug log do chat reflete o rastreamento quando disponível").

Sem `APPAIFORGE_OTEL_TRACES_QUERY_URL` configurada, `fetch_run_trace`
sempre devolve `None` — o chamador cai no comportamento atual (eventos em
memória/Postgres), sem nenhuma tentativa de rede."""

from __future__ import annotations

import httpx

from ..config import get_settings


def fetch_run_trace(run_id: str, *, timeout: float = 3.0) -> list[dict] | None:
    """Spans da execução `run_id`, do mais antigo para o mais novo, ou
    `None` se o Tempo não estiver configurado, a run não tiver nenhum
    trace, ou a consulta falhar (melhor esforço — nunca propaga erro)."""
    base_url = get_settings().otel_traces_query_url
    if not base_url:
        return None
    base_url = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            search = client.get(
                f"{base_url}/api/search", params={"q": f'{{span.run_id="{run_id}"}}', "limit": 1}
            )
            search.raise_for_status()
            traces = (search.json() or {}).get("traces") or []
            if not traces:
                return None
            trace_id = traces[0].get("traceID")
            if not trace_id:
                return None
            trace_response = client.get(f"{base_url}/api/traces/{trace_id}")
            trace_response.raise_for_status()
            return _parse_spans(trace_response.json() or {})
    except Exception:  # noqa: BLE001 - melhor esforço: Tempo fora do ar não derruba o Debug log
        return None


def _parse_spans(trace_payload: dict) -> list[dict]:
    spans: list[dict] = []
    batches = trace_payload.get("batches") or trace_payload.get("resourceSpans") or []
    for batch in batches:
        for scope_spans in batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or []:
            for span in scope_spans.get("spans") or []:
                attributes = {
                    a["key"]: _attr_value(a.get("value") or {})
                    for a in span.get("attributes") or []
                }
                spans.append(
                    {
                        "name": span.get("name", ""),
                        "span_id": span.get("spanId", ""),
                        "parent_span_id": span.get("parentSpanId", ""),
                        "start_time_unix_nano": int(span.get("startTimeUnixNano") or 0),
                        "end_time_unix_nano": int(span.get("endTimeUnixNano") or 0),
                        "attributes": attributes,
                    }
                )
    spans.sort(key=lambda s: s["start_time_unix_nano"])
    return spans


def _attr_value(value: dict) -> object:
    for key in ("stringValue", "boolValue", "intValue", "doubleValue"):
        if key in value:
            return value[key]
    return ""
