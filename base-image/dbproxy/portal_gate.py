"""Cliente HTTP do proxy para o gate no portal (tasks 2.3/4.1).

Auditoria no portal de statements classificadas pelo gate — o endpoint
interno de `portal/appaiforge/main.py`, autenticado por token de serviço
(mesmo padrão do broker da etapa 3). Compartilhado entre os proxies
Postgres e MySQL (task 3.x).

`bloqueada` e `confirmável` em modo enforce nunca chegam ao upstream: o
proxy recusa na hora, sem segurar a conexão nem pedir aprovação a um
humano (uma DELETE/UPDATE sem WHERE restritivo é tratada como destrutiva
igual a um DDL). O único papel deste módulo é registrar essa decisão em
`GateDecision` para a aba Auditoria — uma falha ao falar com o portal aqui
é perda de uma entrada de auditoria, nunca motivo pra impactar a
statement, que já foi recusada ou liberada pelo proxy antes desta chamada.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable

import httpx

PORTAL_INTERNAL_URL = os.environ.get("APPAIFORGE_PORTAL_INTERNAL_URL", "http://portal:8080")
SERVICE_TOKEN = os.environ.get("APPAIFORGE_DB_GATE_PROXY_SERVICE_TOKEN", "")


@dataclasses.dataclass(frozen=True)
class GateContext:
    """Identidade da conexão para a auditoria no portal — quem audita a
    statement precisa saber de qual sistema ela é. Compartilhado entre os
    proxies Postgres e MySQL."""

    system_id: str
    origin: str = "agente"
    connection_name: str = ""


def _headers() -> dict[str, str]:
    return {"x-aidb-dbgate-token": SERVICE_TOKEN}


async def audit_shadow(ctx: GateContext, sql: str, *, log: Callable[..., None] = print, enforced: bool = False) -> None:
    """Audita uma statement classificada sem pendência humana (task 6.1).

    `enforced=False` (modo sombra, default): a statement só foi observada,
    nada foi aplicado. `enforced=True`: chamar DEPOIS que o proxy já
    recusou de verdade em modo enforce (classificação bloqueada ou
    confirmável) — fecha a lacuna achada no roteiro de teste manual, onde
    um `DROP TABLE` recusado não deixava nenhum rastro em `GateDecision`."""
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
