"""Catálogo de provedores de LLM (capability llm-provider-catalog).

Provedores nativos (já previstos pelo catálogo do opencode) e provedores
OpenAI-compatible cadastrados pelo admin. Presets são seedados no boot e na
migration; não podem ser removidos. Toda escrita registra auditoria de gestão.
"""

import re

import httpx
from sqlalchemy import select

from ..db import session_scope
from ..models import LlmProvider, ProviderKey, User
from ..security import decrypt_secret
from . import audit

VALID_KINDS = ("native", "openai-compatible")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")

PRESETS = [
    {"id": "glm", "label": "GLM (Z.ai)", "kind": "native", "provider_id": "zhipuai",
     "base_url": None, "env_name": "ZHIPU_API_KEY", "models": ["glm-4.6"]},
    {"id": "anthropic", "label": "Anthropic", "kind": "native", "provider_id": "anthropic",
     "base_url": None, "env_name": "ANTHROPIC_API_KEY",
     "models": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"]},
    {"id": "openai", "label": "OpenAI", "kind": "native", "provider_id": "openai",
     "base_url": None, "env_name": "OPENAI_API_KEY", "models": ["gpt-4o", "gpt-4o-mini"]},
    {"id": "openrouter", "label": "OpenRouter", "kind": "native", "provider_id": "openrouter",
     "base_url": None, "env_name": "OPENROUTER_API_KEY", "models": []},
]


class NotFound(Exception):
    pass


class PresetProtected(Exception):
    pass


class InvalidProvider(Exception):
    pass


class DiscoveryFailed(Exception):
    """Não foi possível obter a lista de modelos do provedor."""


def _require_admin(actor: User | None) -> None:
    if actor is not None and not actor.is_admin:
        raise PermissionError("gestão do catálogo restrita a administradores")


def _env_name(provider_id: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", provider_id.upper()) + "_API_KEY"


def _to_dict(row: LlmProvider) -> dict:
    return {
        "id": row.id, "label": row.label, "kind": row.kind, "provider_id": row.provider_id,
        "base_url": row.base_url, "env_name": row.env_name, "models": list(row.models or []),
        "is_preset": row.is_preset,
    }


def ensure_presets() -> None:
    """Garante os presets no banco (idempotente; cobre boot via create_all)."""
    with session_scope() as s:
        existing = {p for p in s.execute(select(LlmProvider.id)).scalars().all()}
        for preset in PRESETS:
            if preset["id"] not in existing:
                s.add(LlmProvider(**preset, is_preset=True))


def list_providers() -> list[dict]:
    with session_scope() as s:
        rows = s.execute(select(LlmProvider).order_by(LlmProvider.id)).scalars().all()
        return [_to_dict(r) for r in rows]


def get_provider(provider_id: str) -> dict | None:
    with session_scope() as s:
        row = s.get(LlmProvider, provider_id)
        return _to_dict(row) if row is not None else None


def create_provider(
    provider_id: str, label: str, kind: str, base_url: str | None = None,
    models: list[str] | None = None, actor: User | None = None,
) -> dict:
    _require_admin(actor)
    pid = provider_id.strip().lower()
    if not _ID_RE.match(pid):
        raise InvalidProvider("id deve ser kebab-case: letras minúsculas, dígitos e hífen")
    if kind not in VALID_KINDS:
        raise InvalidProvider(f"tipo inválido: {kind}")
    if kind == "openai-compatible" and not (base_url or "").strip():
        raise InvalidProvider("provedores OpenAI-compatible exigem base_url")
    with session_scope() as s:
        if s.get(LlmProvider, pid) is not None:
            raise InvalidProvider(f"provedor '{pid}' já existe")
        row = LlmProvider(
            id=pid, label=label.strip(), kind=kind, provider_id=pid,
            base_url=(base_url or "").strip() or None,
            env_name=_env_name(pid), models=list(models or []), is_preset=False,
        )
        s.add(row)
        s.flush()
        s.expunge(row)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="provider.create", resource_type="provider", resource_id=pid,
        details={"kind": kind, "base_url": base_url or ""},
    )
    return get_provider(pid)


def update_provider(
    provider_id: str, label: str, base_url: str | None, models: list[str] | None = None,
    actor: User | None = None,
) -> None:
    _require_admin(actor)
    with session_scope() as s:
        row = s.get(LlmProvider, provider_id)
        if row is None:
            raise NotFound("provedor não encontrado")
        row.label = label.strip()
        row.base_url = (base_url or "").strip() or None
        if models is not None:
            row.models = list(models)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="provider.update", resource_type="provider", resource_id=provider_id,
        details={"label": label.strip(), "base_url": base_url or ""},
    )


def set_models(provider_id: str, models: list[str], actor: User | None = None) -> None:
    _require_admin(actor)
    with session_scope() as s:
        row = s.get(LlmProvider, provider_id)
        if row is None:
            raise NotFound("provedor não encontrado")
        row.models = list(models)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="provider.models", resource_type="provider", resource_id=provider_id,
        details={"count": len(models)},
    )


def delete_provider(provider_id: str, actor: User | None = None) -> None:
    _require_admin(actor)
    with session_scope() as s:
        row = s.get(LlmProvider, provider_id)
        if row is None:
            raise NotFound("provedor não encontrado")
        if row.is_preset:
            raise PresetProtected("provedores preset não podem ser removidos")
        s.delete(row)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="provider.remove", resource_type="provider", resource_id=provider_id, details={},
    )


_DEFAULT_MODELS_URL = {
    "openrouter": "https://openrouter.ai/api/v1/models",
    "openai": "https://api.openai.com/v1/models",
}


def _stored_key(provider_id: str) -> str | None:
    with session_scope() as s:
        row = s.get(ProviderKey, provider_id)
        return decrypt_secret(row.key_encrypted) if row is not None else None


# Hosts conhecidos dos provedores nativos, usados pelo proxy HTTP(S) de saída
# (change agent-https-forward-proxy) para calcular a allow-list de um sistema
# sem broker — só hostname público, nenhum segredo. Propósito diferente de
# `_DEFAULT_MODELS_URL` (URL de listagem de modelo, não host de rede) e por
# isso não reaproveitado dali: `anthropic` não lista modelos por API hoje
# (PRESETS acima não tem fetch de lista pra ele), mas tem host bem conhecido
# pra allow-list.
PROVIDER_HOSTS = {
    "openrouter": "openrouter.ai",
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
}


def provider_host(provider: dict) -> str | None:
    """Host real que este provedor configurado alcança sem o broker — usado
    pra calcular a allow-list do proxy HTTP(S) de saída (change
    `agent-https-forward-proxy`). `None` só se um provedor customizado não
    tiver `base_url` (não deveria acontecer: o catálogo exige `base_url`
    para `openai-compatible` na criação)."""
    pid = provider["id"]
    base = (provider.get("base_url") or "").strip()
    if not base and pid == "glm":
        from ..config import get_settings

        base = get_settings().glm_base_url
    if base:
        from urllib.parse import urlparse

        return urlparse(base).hostname
    return PROVIDER_HOSTS.get(pid)


def _models_url(provider: dict) -> str:
    pid = provider["id"]
    base = (provider.get("base_url") or "").strip()
    if not base:
        if pid == "glm":
            from ..config import get_settings

            base = get_settings().glm_base_url
        else:
            return _DEFAULT_MODELS_URL.get(pid, "")
    base = base.rstrip("/")
    if base.endswith("/v1") or base.endswith("/v4"):
        return base + "/models"
    return base + "/v1/models"


def _fetch_models(url: str, key: str | None) -> list[str]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        resp = httpx.get(url, headers=headers, timeout=10)
    except httpx.HTTPError as exc:
        raise DiscoveryFailed(f"falha de rede: {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        raise DiscoveryFailed(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise DiscoveryFailed("resposta inválida do provedor") from exc
    items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    models = [item.get("id") for item in items if isinstance(item, dict) and item.get("id")]
    if not models:
        raise DiscoveryFailed("nenhum modelo retornado pelo provedor")
    return models


def discover_models(provider_id: str, actor: User | None = None) -> list[str]:
    """Obtém a lista de modelos na rota do provedor e guarda no catálogo."""
    _require_admin(actor)
    provider = get_provider(provider_id)
    if provider is None:
        raise NotFound("provedor não encontrado")
    url = _models_url(provider)
    if not url:
        raise DiscoveryFailed(f"provedor '{provider_id}' não tem rota de modelos conhecida")
    models = _fetch_models(url, _stored_key(provider_id))
    set_models(provider_id, models, actor=actor)
    return models