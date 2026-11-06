"""Gestão das chaves de API dos provedores de LLM (capability llm-provider-keys).

A chave é global por provedor **do catálogo** (inclui OpenAI-compatible custom e
OpenRouter), cifrada em repouso (ADR 0007) e nunca devolvida à interface. O teste
usa a rota/base_url do próprio provedor e não grava nada.
"""

import httpx
from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..models import ProviderKey, User
from ..security import decrypt_secret, encrypt_secret
from . import audit, catalog


def _require_admin(actor: User | None) -> None:
    if actor is not None and not actor.is_admin:
        raise PermissionError("gestão de chaves restrita a administradores")


def list_keys() -> list[dict]:
    """Estado por provedor do catálogo: {'provider', 'label', 'configured'}."""
    with session_scope() as s:
        configured = {k.provider for k in s.execute(select(ProviderKey)).scalars().all()}
    return [
        {"provider": p["id"], "label": p["label"], "configured": p["id"] in configured}
        for p in catalog.list_providers()
    ]


def set_key(provider: str, key: str, actor: User | None = None) -> None:
    _require_admin(actor)
    with session_scope() as s:
        row = s.get(ProviderKey, provider)
        if row is not None:
            row.key_encrypted = encrypt_secret(key)
        else:
            s.add(ProviderKey(provider=provider, key_encrypted=encrypt_secret(key)))
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="provider_key.set", resource_type="provider_key", resource_id=provider,
        details={"provider": provider},
    )
    from . import litellm_sync

    litellm_sync.sync_provider(provider)


def remove_key(provider: str, actor: User | None = None) -> None:
    _require_admin(actor)
    with session_scope() as s:
        row = s.get(ProviderKey, provider)
        if row is not None:
            s.delete(row)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="provider_key.remove", resource_type="provider_key", resource_id=provider,
        details={"provider": provider},
    )
    from . import litellm_sync

    litellm_sync.remove_provider(provider)


def _stored_key(provider: str) -> str | None:
    with session_scope() as s:
        row = s.get(ProviderKey, provider)
        return decrypt_secret(row.key_encrypted) if row is not None else None


def _chat_url(provider: dict) -> str:
    pid = provider["id"]
    base = (provider.get("base_url") or "").strip().rstrip("/")
    if base:
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/chat/completions"
    if pid == "glm":
        return get_settings().glm_base_url.rstrip("/") + "/chat/completions"
    if pid == "openrouter":
        return "https://openrouter.ai/api/v1/chat/completions"
    return "https://api.openai.com/v1/chat/completions"


def _model_for(provider: dict) -> str:
    models = provider.get("models") or []
    return models[0] if models else get_settings().default_model


def _probe(provider: dict, key: str) -> tuple[bool, str]:
    """Chamada mínima ao provedor; não grava nada."""
    url = _chat_url(provider)
    model = _model_for(provider)
    try:
        with httpx.Client(timeout=10) as client:
            if provider["id"] == "anthropic":
                resp = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                    json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]},
                )
            else:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]},
                )
        if resp.status_code < 400:
            return True, "ok"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:  # rede/timeout
        return False, f"falha: {exc.__class__.__name__}"


def test_stored_key(provider: str) -> tuple[bool, str]:
    """Testa a chave cadastrada de um provedor (não grava nada)."""
    key = _stored_key(provider)
    if not key:
        return False, "chave não configurada"
    provider_def = catalog.get_provider(provider) or {
        "id": provider, "base_url": None, "models": [], "kind": "native",
    }
    return _probe(provider_def, key)