"""Comandos do agente de cada sistema para o autocomplete do chat (change
add-openspec-to-system-container, D5).

A lista vem do próprio harness do sistema (`HarnessPort.list_commands`), nunca de nomes fixos no
portal. Cache por sistema em memória: 60 s com lista obtida, 10 s quando veio vazia (agente
subindo ou fora do ar — volta a tentar logo). Invalidado quando o container é recriado e ao fim de
cada execução (o agente pode ter criado comandos novos).
"""

import threading
import time

TTL_SECONDS = 60.0
EMPTY_TTL_SECONDS = 10.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict]]] = {}


def _system_dict(system) -> dict:
    get = system.get if isinstance(system, dict) else lambda k, d=None: getattr(system, k, d)
    return {
        "system_id": get("system_id") or get("id"),
        "slug": get("slug"),
        "agent_profile": get("agent_profile"),
    }


def list_for(system) -> list[dict]:
    """Comandos do agente do sistema; lista vazia se o agente não responder."""
    sd = _system_dict(system)
    key = sd["system_id"] or sd["slug"]
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > now:
            return list(hit[1])
    try:
        from ..agent_queue import get_queue

        items = get_queue().harness_for(sd).list_commands(sd) or []
    except Exception:  # noqa: BLE001 - indisponibilidade só esconde as sugestões
        items = []
    items = [
        {"name": str(i["name"]), "description": str(i.get("description") or "")}
        for i in items if isinstance(i, dict) and i.get("name")
    ]
    with _lock:
        _cache[key] = (now + (TTL_SECONDS if items else EMPTY_TTL_SECONDS), items)
    return list(items)


def invalidate(system_id: str | None = None) -> None:
    with _lock:
        if system_id is None:
            _cache.clear()
        else:
            _cache.pop(system_id, None)
