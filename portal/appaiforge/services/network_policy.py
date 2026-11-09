"""Controles por sistema do proxy HTTP(S) de saída (change
`agent-https-forward-proxy`, D6/D7/D8): internet habilitada, modo restrito e
a lista de domínios do modo restrito. RBAC igual à aba Conexões — chamador
decide quem pode chamar, este módulo só aplica a regra de rede."""

from __future__ import annotations

import threading

from sqlalchemy import select

from .. import telemetry
from ..db import session_scope
from ..models import AllowedDomain, System
from ..provisioning import PACKAGE_REGISTRY_HOSTS, default_https_allowlist

_log = telemetry.get_logger()


class SystemNotFound(Exception):
    pass


# Serializa o refresh do sidecar por sistema (achado real de teste de
# integração): dois toggles em sequência rápida (ex.: internet habilitada
# e, logo depois, modo restrito) cada um dispara sua própria thread de
# refresh — sem isto, as duas corriam pra recriar o MESMO nome de
# container ao mesmo tempo e uma delas batia um 409 Conflict do Docker. O
# dict em si é protegido por um lock à parte, só pra criar a entrada por
# sistema (operação rápida, nunca seguro pelo lock pesado do Docker).
_sidecar_locks: dict[str, threading.Lock] = {}
_sidecar_locks_guard = threading.Lock()


def _sidecar_lock(system_id: str) -> threading.Lock:
    with _sidecar_locks_guard:
        lock = _sidecar_locks.get(system_id)
        if lock is None:
            lock = threading.Lock()
            _sidecar_locks[system_id] = lock
        return lock


def _get_system(s, system_id: str) -> System:
    system = s.get(System, system_id)
    if system is None:
        raise SystemNotFound(system_id)
    return system


def list_allowed_domains(system_id: str) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(AllowedDomain).where(AllowedDomain.system_id == system_id).order_by(AllowedDomain.domain)
        ).scalars().all()
        return [{"id": r.id, "domain": r.domain, "author_id": r.author_id, "created_at": r.created_at.isoformat()} for r in rows]


def add_allowed_domain(system_id: str, domain: str, author_id: str | None = None) -> dict | None:
    """Cadastra um domínio; devolve `None` (idempotente) se já existir —
    mesma postura de "sem duplicar" da pré-população (task 4.2)."""
    domain = domain.strip().lower()
    if not domain:
        return None
    with session_scope() as s:
        exists = s.execute(
            select(AllowedDomain).where(AllowedDomain.system_id == system_id, AllowedDomain.domain == domain)
        ).scalar_one_or_none()
        if exists is not None:
            return None
        row = AllowedDomain(system_id=system_id, domain=domain, author_id=author_id)
        s.add(row)
        s.flush()
        result = {"id": row.id, "domain": row.domain}
        s.expunge(row)
    _log.info(
        "domínio liberado adicionado",
        extra={"system_id": system_id, "author_id": author_id, "domain": domain},
    )
    _refresh_sidecar_async(system_id)
    return result


def remove_allowed_domain(system_id: str, domain_id: str, author_id: str | None = None) -> bool:
    with session_scope() as s:
        row = s.get(AllowedDomain, domain_id)
        if row is None or row.system_id != system_id:
            return False
        domain = row.domain
        s.delete(row)
    _log.info(
        "domínio liberado removido",
        extra={"system_id": system_id, "author_id": author_id, "domain": domain},
    )
    _refresh_sidecar_async(system_id)
    return True


def seed_default_domains_if_empty(system_id: str) -> None:
    """Pré-popula a lista do modo restrito com os registros de pacote mais
    usados (task 4.2) — só se o sistema ainda não tiver NENHUM domínio
    cadastrado, pra não duplicar nem apagar o que o editor já alterou ao
    ligar/desligar o modo restrito mais de uma vez."""
    with session_scope() as s:
        has_any = s.execute(
            select(AllowedDomain.id).where(AllowedDomain.system_id == system_id).limit(1)
        ).scalar_one_or_none()
        if has_any is not None:
            return
        for host, _port in PACKAGE_REGISTRY_HOSTS:
            s.add(AllowedDomain(system_id=system_id, domain=host))


def _refresh_sidecar_async(system_id: str) -> None:
    """Aplica a allow-list recalculada ao sidecar fora do request (mesmo
    padrão de `connections._refresh_provisioning`) — recria só o sidecar do
    proxy HTTP(S), não o container do agente (ver `refresh_https_allowlist`).

    Serializado por sistema (`_sidecar_lock`): duas chamadas em sequência
    rápida (ex.: dois toggles seguidos) cada uma dispara sua própria
    thread, e sem o lock elas corriam pra recriar o mesmo nome de
    container ao mesmo tempo — achado real de teste de integração (409
    Conflict do Docker). Quem espera a vez sempre lê o estado mais recente
    do sistema (`get_system` de novo, não um snapshot antigo), então
    nenhuma chamada fica com um resultado desatualizado por causa da fila."""
    import logging
    import threading

    log = logging.getLogger(__name__)

    def work() -> None:
        try:
            from ..provisioning import refresh_https_allowlist
            from .systems import get_system

            with _sidecar_lock(system_id):
                system = get_system(system_id)
                if system is not None:
                    refresh_https_allowlist(system)
        except Exception:
            log.exception("não foi possível aplicar a allow-list ao sidecar do sistema %s", system_id)

    threading.Thread(target=work, daemon=True, name=f"refresh-httpsproxy-{system_id}").start()


def set_internet_enabled(system_id: str, enabled: bool, author_id: str | None = None) -> None:
    with session_scope() as s:
        system = _get_system(s, system_id)
        system.internet_enabled = enabled
    _log.info(
        "acesso à internet alterado",
        extra={"system_id": system_id, "author_id": author_id, "enabled": enabled},
    )
    _refresh_sidecar_async(system_id)


def set_restricted_network(system_id: str, restricted: bool, author_id: str | None = None) -> None:
    """Ligar o modo restrito pré-popula a lista na primeira vez (task 4.2) —
    desligar não mexe na lista, ela só fica sem efeito enquanto desligada."""
    with session_scope() as s:
        system = _get_system(s, system_id)
        system.restricted_network = restricted
    _log.info(
        "modo restrito de rede alterado",
        extra={"system_id": system_id, "author_id": author_id, "restricted": restricted},
    )
    if restricted:
        seed_default_domains_if_empty(system_id)
    _refresh_sidecar_async(system_id)


def final_https_allowlist(system: System) -> list[tuple[str, int]]:
    """Allow-list final do proxy HTTP(S) de saída pra este sistema (task
    4.3): `internet_enabled=False` esvazia tudo (D6); senão,
    `restricted_network=True` substitui a allow-list padrão pela lista de
    domínios cadastrada, porta 443 (D7); senão, a allow-list padrão (D2)."""
    if not system.internet_enabled:
        return []
    if system.restricted_network:
        domains = list_allowed_domains(system.id)
        return [(d["domain"], 443) for d in domains]
    return default_https_allowlist(system)
