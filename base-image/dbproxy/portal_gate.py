"""Cliente HTTP do proxy para o gate no portal (tasks 2.3/4.1).

Pedido de aprovação de uma statement confirmável e espera poll-ando até
decisão (aprovada/recusada) ou expiração — os endpoints internos de
`portal/appaiforge/main.py`, autenticados por token de serviço (mesmo
padrão do broker da etapa 3). Compartilhado entre os proxies Postgres e
MySQL (task 3.x).

O desfecho "expirada" dos três da task 2.3 é o prazo do próprio pedido no
portal (`expires_at`, task 4.1) — o portal expira preguiçosamente na
consulta, então o próximo poll já devolve "expirada". Uma falha de rede
intermitente durante o poll não aborta a espera (o portal pode reiniciar; o
pedido continua existindo) — só um status final decide, até um teto próprio
do proxy (`max_wait_seconds`, task 4.3): se o portal ficar inalcançável *ou*
sem decidir por mais tempo que isso, o poll desiste e levanta
`PortalUnavailable` — sem esse teto, uma rede permanentemente fora do ar
travaria a espera para sempre, e o cliente (psql, app) ficaria pendurado
indefinidamente em vez de receber um erro. Falha ao *criar* o pedido, por
outro lado, levanta na hora: sem pedido registrado não há o que esperar, e
a postura segura é recusar.

O run/sessão associados ao pedido são resolvidos pelo portal (task 4.2,
mesma atribuição do broker) — o proxy só manda `system_id`; não há campo de
run aqui porque confiar no que o cliente alega abriria a porta pra atribuir
a decisão à run errada.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
from collections.abc import Callable

import httpx

PORTAL_INTERNAL_URL = os.environ.get("APPAIFORGE_PORTAL_INTERNAL_URL", "http://portal:8080")
SERVICE_TOKEN = os.environ.get("APPAIFORGE_DB_GATE_PROXY_SERVICE_TOKEN", "")
POLL_INTERVAL_SECONDS = float(os.environ.get("APPAIFORGE_DB_GATE_POLL_INTERVAL_SECONDS", "0.5"))
# Teto independente do prazo do pedido no portal (`db_gate_approval_timeout_seconds`,
# default 120s lá) — generoso o bastante pra cobrir isso com folga sem depender
# de o proxy conhecer a configuração do portal.
MAX_WAIT_SECONDS = float(os.environ.get("APPAIFORGE_DB_GATE_MAX_WAIT_SECONDS", "300"))


class PortalUnavailable(RuntimeError):
    """Portal inalcançável ou recusou o pedido — o chamador trata como recusa segura."""


@dataclasses.dataclass(frozen=True)
class GateContext:
    """Identidade da conexão para o pedido de aprovação no portal — quem
    decide a statement precisa saber de qual sistema ela é. Compartilhado
    entre os proxies Postgres e MySQL."""

    system_id: str
    origin: str = "agente"
    connection_name: str = ""


def _headers() -> dict[str, str]:
    return {"x-aidb-dbgate-token": SERVICE_TOKEN}


async def request_approval(
    client: httpx.AsyncClient, system_id: str, sql: str, *,
    origin: str, connection_name: str = "", reason: str = "",
) -> str:
    """Registra o pedido pendente; devolve o id."""
    payload = {
        "system_id": system_id, "sql": sql, "origin": origin,
        "connection_name": connection_name, "reason": reason,
    }
    try:
        resp = await client.post(
            f"{PORTAL_INTERNAL_URL}/internal/db-gate/requests", json=payload, headers=_headers()
        )
    except httpx.HTTPError as exc:
        raise PortalUnavailable(f"falha ao registrar pedido de aprovação: {exc}") from exc
    if resp.status_code != 201:
        raise PortalUnavailable(f"portal recusou o pedido de aprovação: {resp.status_code} {resp.text}")
    return resp.json()["id"]


async def wait_decision(client: httpx.AsyncClient, request_id: str, *,
                        poll_interval: float = POLL_INTERVAL_SECONDS,
                        max_wait_seconds: float = MAX_WAIT_SECONDS) -> str:
    """Poll até o status saír de "pendente". Devolve aprovada/recusada/expirada,
    ou levanta `PortalUnavailable` se `max_wait_seconds` estourar sem resposta
    final — teto independente da expiração do pedido no portal, que cobre o
    caso do portal ficar inalcançável (task 4.3)."""
    url = f"{PORTAL_INTERNAL_URL}/internal/db-gate/requests/{request_id}"
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_wait_seconds
    while True:
        try:
            resp = await client.get(url, headers=_headers())
        except httpx.HTTPError:
            resp = None
        if resp is not None and resp.status_code == 200:
            status = resp.json()["status"]
            if status != "pendente":
                return status
        elif resp is not None:
            raise PortalUnavailable(f"portal recusou a consulta do pedido: {resp.status_code} {resp.text}")
        if loop.time() >= deadline:
            raise PortalUnavailable(
                f"sem decisão final após {max_wait_seconds:.0f}s de espera (portal inalcançável ou pedido nunca sai de pendente)"
            )
        await asyncio.sleep(poll_interval)


async def request_and_wait(
    system_id: str, sql: str, *, origin: str, connection_name: str = "", reason: str = "",
    poll_interval: float = POLL_INTERVAL_SECONDS, max_wait_seconds: float = MAX_WAIT_SECONDS,
) -> str:
    """Conveniência para o caminho comum: cria o pedido e espera o desfecho
    numa única chamada, com seu próprio `httpx.AsyncClient`."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        request_id = await request_approval(
            client, system_id, sql, origin=origin, connection_name=connection_name, reason=reason,
        )
        return await wait_decision(client, request_id, poll_interval=poll_interval, max_wait_seconds=max_wait_seconds)


async def decide_confirmable(
    ctx: GateContext, sql: str, reason: str, *,
    log: Callable[..., None] = print, max_wait_seconds: float = MAX_WAIT_SECONDS,
) -> str:
    """aprovada/recusada/expirada — usado pelos dois proxies (Postgres e
    MySQL) no hold da confirmável. Falha ao falar com o portal, ou estourar
    `max_wait_seconds` sem decisão final, é recusa segura — não uma
    statement liberada por omissão."""
    try:
        return await request_and_wait(ctx.system_id, sql, origin=ctx.origin,
                                      connection_name=ctx.connection_name, reason=reason,
                                      max_wait_seconds=max_wait_seconds)
    except PortalUnavailable as exc:
        log("portal indisponível para decidir confirmável, recusando por segurança:", exc)
        return "recusada"


async def audit_shadow(ctx: GateContext, sql: str, *, log: Callable[..., None] = print, enforced: bool = False) -> None:
    """Audita uma statement classificada sem pendência humana — nunca
    segura nem recusa por conta própria (task 6.1). Uma falha ao falar com
    o portal aqui é perda de uma auditoria, não motivo pra impactar a
    statement.

    `enforced=False` (modo sombra, default): a statement só foi observada,
    nada foi aplicado. `enforced=True`: chamar DEPOIS que o proxy já
    recusou de verdade em modo enforce (classificação bloqueada) — fecha a
    lacuna achada no roteiro de teste manual, onde um `DROP TABLE` recusado
    não deixava nenhum rastro em `GateDecision`."""
    payload = {
        "system_id": ctx.system_id, "sql": sql, "origin": ctx.origin, "connection_name": ctx.connection_name,
        "enforced": enforced,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            resp = await client.post(f"{PORTAL_INTERNAL_URL}/internal/db-gate/audit", json=payload, headers=_headers())
        if resp.status_code != 200:
            log("auditoria recusada pelo portal:", resp.status_code, resp.text)
    except httpx.HTTPError as exc:
        log("falha ao auditar (statement segue normalmente):", exc)
