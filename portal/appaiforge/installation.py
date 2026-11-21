"""Identidade desta instalação do portal (change add-production-portal-install, D1).

O identificador fica em `portal_instance.installation_id`, gravado por
`auth_mode.enforce_mode_lock` no boot. Ele distingue duas instalações com bancos
diferentes e vai num rótulo dos containers que o driver Docker cria (D2).
"""

from __future__ import annotations

INSTALLATION_LABEL = "appaiforge.installation"

_cached: str | None = None


def installation_id() -> str:
    """Identificador desta instalação; cria a linha (ou completa uma antiga) se o boot
    ainda não passou por aqui, como em testes que provisionam sem subir o app."""
    global _cached
    if _cached is None:
        from .auth_mode import enforce_mode_lock
        from .db import session_scope
        from .models import PortalInstance

        with session_scope() as s:
            row = s.get(PortalInstance, 1)
            value = row.installation_id if row is not None else None
        if not value:
            enforce_mode_lock()
            with session_scope() as s:
                value = s.get(PortalInstance, 1).installation_id
        _cached = value
    return _cached


def reset_cache() -> None:
    """Esquece o valor em cache (testes que recriam o banco)."""
    global _cached
    _cached = None


def owner_description(labels: dict | None, system_id: str, current: str) -> str | None:
    """Dono de um container existente com o nome que o sistema `system_id` usaria (D2).

    Devolve `None` se o container é deste portal para este sistema; senão, uma descrição
    curta do dono para a mensagem de erro. Sem rótulo de instalação (container anterior a
    esta versão), vale o identificador do sistema."""
    labels = labels or {}
    if labels.get("appaiforge.managed") != "true":
        return "um container que o portal não criou"
    other = labels.get(INSTALLATION_LABEL)
    if other and other != current:
        return f"outra instalação do portal ({other[:8]})"
    if labels.get("appaiforge.system_id") != system_id:
        return "outro sistema"
    return None


class SharedDockerHost(RuntimeError):
    """Portal de produção num host Docker com containers de outra instalação (D3)."""


def foreign_containers(containers: list[tuple[str, dict]], known_system_ids: set[str], current: str) -> list[str]:
    """Nomes dos containers gerenciados que não são desta instalação: com outro rótulo de
    instalação ou, sem rótulo, com um sistema que não existe neste banco (D3)."""
    foreign = []
    for name, labels in containers:
        labels = labels or {}
        if labels.get("appaiforge.managed") != "true":
            continue
        other = labels.get(INSTALLATION_LABEL)
        if other:
            if other != current:
                foreign.append(name)
        elif labels.get("appaiforge.system_id") not in known_system_ids:
            foreign.append(name)
    return sorted(foreign)


def check_docker_host() -> None:
    """No boot de um portal de produção com driver Docker, recusa subir se o host tem
    containers de outra instalação. Com `allow_shared_docker_host`, só avisa."""
    import logging

    from sqlalchemy import select

    from .config import get_settings
    from .db import session_scope
    from .models import System

    settings = get_settings()
    if settings.provisioning_driver != "docker" or settings.installation_role != "production":
        return
    from .provisioning import _docker

    listed = _docker().containers.list(all=True, filters={"label": "appaiforge.managed=true"})
    with session_scope() as s:
        known = set(s.execute(select(System.id)).scalars())
    foreign = foreign_containers([(c.name, c.labels) for c in listed], known, installation_id())
    if not foreign:
        return
    shown = ", ".join(foreign[:10]) + (f" e mais {len(foreign) - 10}" if len(foreign) > 10 else "")
    if settings.allow_shared_docker_host:
        logging.getLogger(__name__).warning(
            "host Docker compartilhado com outra instalação (APPAIFORGE_ALLOW_SHARED_DOCKER_HOST, "
            "só para testes): %s", shown)
        return
    raise SharedDockerHost(
        f"este portal é de produção e o host Docker tem containers de outra instalação: {shown}. "
        "Produção precisa de um host Docker próprio. Se algum deles for um resto deste portal, "
        "confira com `docker inspect` e remova antes de subir."
    )
