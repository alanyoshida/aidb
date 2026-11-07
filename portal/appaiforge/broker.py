"""Helpers do broker de inferência (etapa 3, ADR 0020).

Funções puras de extração/validação do token opaco e o cliente que resolve
o contexto da execução no portal. Mantidas fora do ASGI para testar sem
subir servidor.
"""

import httpx
from urllib.parse import urlparse

from . import inference_token
from .config import get_settings


def bearer_token(authorization: str | None) -> str | None:
    """Extrai o token de um header `Authorization: Bearer <token>`."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def system_id_from_token(token: str | None) -> str | None:
    """O system_id é o prefixo antes do ponto; a assinatura não é decodificada aqui."""
    if not token or "." not in token:
        return None
    system_id = token.split(".", 1)[0]
    return system_id or None


def validate_token(token: str | None, version: int) -> str | None:
    """Valida a assinatura para a versão vigente; devolve o system_id ou None."""
    if not token:
        return None
    return inference_token.validate(token, version)


def outbound_headers(headers: dict[str, str], api_key: str) -> dict[str, str]:
    """Descarta a credencial do cliente e injeta a chave do broker no caminho de saída."""
    out = {
        k: v for k, v in headers.items()
        if k.lower() not in {"authorization", "x-api-key", "host", "content-length"}
    }
    if api_key:
        out["Authorization"] = f"Bearer {api_key}"
    return out


def apply_context(body: dict, context: dict) -> dict:
    """Injeta metadata e reescreve o model para o nome canônico do LiteLLM.

    O agente envia só o modelID; o nome que existe no LiteLLM é
    `<provider_id>/<model>` (mesma regra de litellm_sync) — reescrever aqui
    também impede que o agente peça um modelo fora do catálogo do sistema."""
    meta = body.setdefault("metadata", {})
    if isinstance(meta, dict):
        for key in ("system_id", "run_id", "chat_session_id"):
            if context.get(key) is not None:
                meta.setdefault(key, context[key])
    if context.get("litellm_model"):
        body["model"] = context["litellm_model"]
    return body


def destination_allowed(url: str, allowed_hosts: str) -> bool:
    """Confere se o host de destino está na allowlist configurada."""
    host = (urlparse(url).hostname or "").lower()
    allowed = {h.strip().lower() for h in allowed_hosts.split(",") if h.strip()}
    return bool(host) and host in allowed


async def resolve_context(system_id: str) -> dict | None:
    """Consulta o portal pelo contexto ativo do sistema (versão, run, sessão, provedor)."""
    settings = get_settings()
    url = f"{settings.portal_internal_url.rstrip('/')}/internal/inference/context"
    headers = {"X-AIDB-Broker-Token": settings.inference_broker_service_token}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"system_id": system_id}, headers=headers)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


def cancel_inference(run_id: str) -> None:
    """Pede ao broker que encerre a conexão upstream da execução (best-effort)."""
    settings = get_settings()
    url = f"{settings.inference_broker_url.rstrip('/')}/internal/cancel"
    headers = {"X-AIDB-Broker-Token": settings.inference_broker_service_token}
    try:
        httpx.post(url, json={"run_id": run_id}, headers=headers, timeout=3.0)
    except httpx.HTTPError:
        # broker desligado/indisponível: o harness já foi interrompido
        pass
