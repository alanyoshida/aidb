"""Modo de autenticação do portal e sua trava na base (change add-oidc-sso, D1).

O modo (`local` | `oidc`) vem de `APPAIFORGE_AUTH_MODE`, é gravado em `portal_instance`
no primeiro boot e não pode mudar depois: trocar o modo de uma instalação existente
deixaria donos órfãos e usuários duplicados sem nenhum sinal, então o boot é recusado.
"""

from sqlalchemy import exists, select

from .config import Settings, get_settings
from .db import session_scope
from .models import PortalInstance, User

MODES = ("local", "oidc")

# Configurações obrigatórias no modo oidc -> nome da variável de ambiente.
_OIDC_REQUIRED = {
    "oidc_issuer": "APPAIFORGE_OIDC_ISSUER",
    "oidc_client_id": "APPAIFORGE_OIDC_CLIENT_ID",
    "oidc_client_secret": "APPAIFORGE_OIDC_CLIENT_SECRET",
    "public_base_url": "APPAIFORGE_PUBLIC_BASE_URL",
}


class AuthConfigError(RuntimeError):
    """Configuração de autenticação inválida ou incompleta — o portal não sobe."""


class AuthModeMismatch(RuntimeError):
    """Modo configurado diverge do gravado na instalação — o portal não sobe."""


def current_mode() -> str:
    return get_settings().auth_mode


def is_oidc() -> bool:
    return current_mode() == "oidc"


def validate_config(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.auth_mode not in MODES:
        raise AuthConfigError(
            f"APPAIFORGE_AUTH_MODE inválido: {settings.auth_mode!r} (use 'local' ou 'oidc')"
        )
    if settings.auth_mode == "oidc":
        missing = [env for field, env in _OIDC_REQUIRED.items() if not getattr(settings, field).strip()]
        if missing:
            raise AuthConfigError(
                "modo oidc sem configuração obrigatória: " + ", ".join(missing)
            )


def enforce_mode_lock() -> str:
    """Grava o modo no primeiro boot ou recusa um modo divergente do gravado.

    Sem linha gravada mas com usuários comuns na base, a instalação é anterior a esta
    change (só existia o modo local): grava `local` antes de comparar. Isso cobre bases
    criadas por `create_all` sem a migração Alembic que faz o mesmo.
    """
    configured = current_mode()
    with session_scope() as s:
        row = s.get(PortalInstance, 1)
        if row is None:
            has_users = s.execute(
                select(exists().where(User.break_glass.is_(False)))
            ).scalar()
            row = PortalInstance(id=1, auth_mode="local" if has_users else configured)
            s.add(row)
        recorded = row.auth_mode
    if recorded != configured:
        raise AuthModeMismatch(
            f"APPAIFORGE_AUTH_MODE={configured!r} diverge do modo gravado nesta instalação "
            f"({recorded!r}). Trocar o modo de autenticação de uma instalação existente não é "
            "suportado; volte a configuração para o modo gravado."
        )
    return recorded


def check_on_boot() -> str:
    validate_config()
    return enforce_mode_lock()
