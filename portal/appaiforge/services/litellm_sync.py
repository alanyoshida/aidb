"""Sincroniza as chaves do catálogo com o LiteLLM (etapa 3, ADR 0020).

O portal continua sendo a fonte única das chaves (cifradas no Postgres, ADR
0007). Quando uma chave muda (ou no boot), o portal empurra os deployments
para a API administrativa do LiteLLM; o container do agente nunca vê a chave.
"""

import logging

import httpx

from ..config import get_settings
from . import catalog, provider_keys

log = logging.getLogger(__name__)


def _litellm_params(provider: dict, model: str, key: str) -> dict:
    pid = provider["id"]
    base = (provider.get("base_url") or "").strip() or None
    if provider["kind"] == "openai-compatible":
        return {"model": f"openai/{model}", "api_key": key, "api_base": base}
    if pid == "glm":
        return {
            "model": f"openai/{model}",
            "api_key": key,
            "api_base": base or get_settings().glm_base_url,
        }
    if pid == "openrouter":
        return {"model": f"openrouter/{model}", "api_key": key}
    if pid == "anthropic":
        return {"model": f"anthropic/{model}", "api_key": key}
    params = {"model": f"openai/{model}", "api_key": key}
    if base:
        params["api_base"] = base
    return params


def deployments_for(provider: dict, key: str) -> list[dict]:
    """Deployments do LiteLLM para os modelos do provedor, com nome que o agente envia."""
    provider_id = provider.get("provider_id") or provider["id"]
    return [
        {
            "model_name": f"{provider_id}/{model}",
            "litellm_params": _litellm_params(provider, model, key),
            "model_info": {"id": f"aidb:{provider_id}/{model}"},
        }
        for model in (provider.get("models") or [])
    ]


def _admin(method: str, path: str, payload: dict, timeout: float = 10.0) -> httpx.Response:
    settings = get_settings()
    url = f"{settings.litellm_base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {settings.litellm_api_key}"}
    return httpx.request(method, url, headers=headers, json=payload, timeout=timeout)


def _enabled() -> bool:
    settings = get_settings()
    # Só sincroniza durante o rollout do broker; com a flag desligada o LiteLLM
    # não é usado e não deve receber chamadas da administração.
    return bool(
        settings.inference_broker_enabled
        and settings.litellm_api_key
        and settings.litellm_base_url
    )


def _delete_deployment(model_name: str, timeout: float = 10.0) -> None:
    try:
        _admin("POST", "/model/delete", {"id": f"aidb:{model_name}"}, timeout=timeout)
    except httpx.HTTPError:
        pass


def sync_provider(provider_id: str, timeout: float = 10.0) -> None:
    """Empurra os deployments de um provedor com chave cadastrada (best-effort)."""
    if not _enabled():
        return
    provider = catalog.get_provider(provider_id)
    if provider is None:
        return
    key = provider_keys._stored_key(provider_id)
    if not key:
        return
    for deployment in deployments_for(provider, key):
        _delete_deployment(deployment["model_name"], timeout=timeout)
        try:
            _admin("POST", "/model/new", deployment, timeout=timeout)
        except httpx.HTTPError as exc:
            log.warning("litellm: falha ao sincronizar %s: %s", deployment["model_name"], exc)


def remove_provider(provider_id: str, timeout: float = 3.0) -> None:
    """Remove os deployments de um provedor que teve a chave removida."""
    if not _enabled():
        return
    provider = catalog.get_provider(provider_id)
    if provider is None:
        return
    for deployment in deployments_for(provider, key="removed"):
        _delete_deployment(deployment["model_name"], timeout=timeout)


def sync_all(timeout: float = 3.0) -> None:
    """Sincroniza todos os provedores com chave (boot do portal)."""
    if not _enabled():
        return
    for provider in catalog.list_providers():
        if provider_keys._stored_key(provider["id"]):
            sync_provider(provider["id"], timeout=timeout)
