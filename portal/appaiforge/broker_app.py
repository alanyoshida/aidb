"""Broker de inferência (etapa 3, ADR 0020).

Serviço ASGI dedicado que recebe as chamadas do agente, valida o token
opaco e encaminha ao LiteLLM com a credencial injetada no caminho de saída.
Nesta base (task 3.1) o serviço expõe health e o roteamento por dialeto;
validação de token, resolução de contexto, allowlist e cancelamento entram
nas tasks seguintes.
"""

import asyncio
import hmac
import json
import logging

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .broker import (
    apply_context,
    bearer_token,
    destination_allowed,
    outbound_headers,
    resolve_context,
    system_id_from_token,
    validate_token,
)
from .config import get_settings
from . import telemetry

log = logging.getLogger(__name__)

telemetry.configure("appaiforge-broker")

app = FastAPI(title="AIDB Inference Broker")

# Conexões upstream em andamento por run, para o portal cancelar de fato.
_inflight: dict[str, set] = {}
_inflight_lock = asyncio.Lock()


async def _register_inflight(run_id: str, response) -> None:
    async with _inflight_lock:
        _inflight.setdefault(run_id, set()).add(response)


async def _unregister_inflight(run_id: str, response) -> None:
    async with _inflight_lock:
        responses = _inflight.get(run_id)
        if responses is not None:
            responses.discard(response)
            if not responses:
                _inflight.pop(run_id, None)


async def _cancel_inflight(run_id: str) -> int:
    async with _inflight_lock:
        responses = list(_inflight.pop(run_id, set()))
    for response in responses:
        try:
            await response.aclose()
        except Exception:  # noqa: BLE001 - encerramento best-effort
            pass
    return len(responses)

_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailers", "transfer-encoding", "upgrade"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "inference-broker"}


def _upstream(path: str) -> str:
    base = get_settings().litellm_base_url.rstrip("/")
    return f"{base}/{path.lstrip('/')}"


async def _forward(request: Request, path: str, context: dict | None = None) -> Response:
    """Encaminha a requisição ao LiteLLM repassando o corpo em streaming."""
    settings = get_settings()
    url = _upstream(path)
    if not destination_allowed(url, settings.inference_broker_allowed_hosts):
        return JSONResponse(status_code=403, content={"error": "destino de inferência não permitido"})
    headers = outbound_headers(dict(request.headers), settings.litellm_api_key)
    content = await request.body()
    if context and content:
        try:
            body = json.loads(content)
            if isinstance(body, dict):
                content = json.dumps(apply_context(body, context)).encode()
        except (ValueError, TypeError):
            pass
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
    upstream_request = client.build_request(
        request.method, url, headers=headers, content=content or None
    )
    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        log.warning("broker: falha ao alcançar o LiteLLM: %s", exc)
        return JSONResponse(status_code=502, content={"error": "backend de inferência indisponível"})

    run_id = context.get("run_id") if context else None
    if run_id:
        await _register_inflight(run_id, upstream_response)

    async def body_iter():
        try:
            async for chunk in upstream_response.aiter_raw():
                yield chunk
        finally:
            await upstream_response.aclose()
            await client.aclose()
            if run_id:
                await _unregister_inflight(run_id, upstream_response)

    response_headers = {
        k: v for k, v in upstream_response.headers.items()
        if k.lower() not in _HOP_BY_HOP | {"content-length"}
    }
    return StreamingResponse(
        body_iter(), status_code=upstream_response.status_code, headers=response_headers
    )


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_v1(path: str, request: Request) -> Response:
    """Espelha o dialeto do agente: /v1/chat/completions, /v1/responses e /v1/messages."""
    token = bearer_token(request.headers.get("authorization"))
    system_id = system_id_from_token(token)
    if token is None or system_id is None:
        return JSONResponse({"error": "token de inferência ausente ou malformado"}, status_code=401)

    context = await resolve_context(system_id)
    if context is None:
        return JSONResponse({"error": "sistema não encontrado ou broker sem autorização"}, status_code=401)
    if validate_token(token, int(context.get("version", 0))) != system_id:
        return JSONResponse({"error": "token de inferência inválido ou revogado"}, status_code=401)
    if not context.get("run_id"):
        return JSONResponse({"error": "sistema sem execução ativa"}, status_code=409)
    if context.get("session_revoked"):
        return JSONResponse({"error": "inferência revogada para esta sessão"}, status_code=403)

    run_id = context["run_id"]
    span = telemetry.start_child_span(run_id, "llm.request", attributes={"system_id": system_id, "path": path})
    try:
        return await _forward(request, f"v1/{path}", context)
    finally:
        span.end()


@app.post("/internal/cancel")
async def internal_cancel(request: Request) -> Response:
    """Chamado pelo portal na interrupção: encerra a conexão upstream da run."""
    settings = get_settings()
    supplied = request.headers.get("x-aidb-broker-token", "")
    if not settings.inference_broker_service_token or not hmac.compare_digest(
        supplied, settings.inference_broker_service_token
    ):
        return JSONResponse({"error": "não autorizado"}, status_code=401)
    payload = await request.json()
    run_id = (payload or {}).get("run_id")
    if not run_id:
        return JSONResponse({"error": "run_id obrigatório"}, status_code=400)
    return JSONResponse({"cancelled": await _cancel_inflight(run_id)})
