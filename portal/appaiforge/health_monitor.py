"""Monitor de saúde das apps geradas (spec app-serving).

Sonda periodicamente a app de cada sistema ativo; falhas consecutivas marcam
o sistema como erro (visível na página), recuperação volta a ativo sem
intervenção. O reinício em si é do supervisor do container (ADR 0003).

A sonda em si é responsabilidade do driver ativo (`ProvisioningDriver.is_healthy`,
change `add-kubernetes-driver`) — o driver Docker sonda HTTP direto, igual sempre;
o driver Kubernetes lê o resultado da `readinessProbe` via API, porque o portal
roda fora do cluster e não alcança a rede do Pod.
"""

import logging
import os
import re
import threading
import time

from sqlalchemy import select

from .db import session_scope
from .models import System, SystemStatus

log = logging.getLogger(__name__)

_FAIL_THRESHOLD = 3
_fail_counts: dict[str, int] = {}


def check_once() -> dict[str, bool]:
    """Uma rodada de checagem; devolve {slug: saudável}.

    Sonda sistemas ativos e também os em erro por app fora do ar (para
    detectar recuperação sem intervenção).
    """
    with session_scope() as s:
        systems = [
            (sys.id, sys.slug)
            for sys in s.execute(select(System).where(System.status.in_([SystemStatus.active, SystemStatus.error])))
            .scalars()
            if sys.status == SystemStatus.active or (sys.status_message or "").startswith("app fora do ar")
        ]

    from .drivers import get_driver

    driver = get_driver()
    results: dict[str, bool] = {}
    for system_id, slug in systems:
        healthy = driver.is_healthy(slug)
        results[slug] = healthy
        if healthy:
            _fail_counts[slug] = 0
            _clear_if_needed(system_id, slug)
        else:
            _fail_counts[slug] = _fail_counts.get(slug, 0) + 1
            if _fail_counts[slug] >= _FAIL_THRESHOLD:
                _set(system_id, SystemStatus.error, f"app fora do ar ({_fail_counts[slug]} checagens)")
    return results


def _clear_if_needed(system_id: str, slug: str) -> None:
    """App saudável: limpa a marca de app-fora-do-ar (volta a ativo) ou a mensagem."""
    with session_scope() as s:
        system = s.get(System, system_id)
        if system is None:
            return
        message = system.status_message or ""
        if system.status == SystemStatus.error and message.startswith("app fora do ar"):
            system.status = SystemStatus.active
            system.status_message = ""
        elif system.status == SystemStatus.active and message:
            system.status_message = ""


def _set(system_id: str, status: SystemStatus, message: str) -> None:
    from .services.systems import set_status

    set_status(system_id, status, message)


def start_monitor(interval: float | None = None) -> threading.Thread:
    seconds = interval if interval is not None else float(os.environ.get("APPAIFORGE_HEALTH_INTERVAL", "15"))

    def loop() -> None:
        while True:
            try:
                check_once()
            except Exception:
                log.exception("health check falhou")
            time.sleep(seconds)

    thread = threading.Thread(target=loop, daemon=True, name="health-monitor")
    thread.start()
    return thread
