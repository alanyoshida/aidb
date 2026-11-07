"""Orquestrador do sidecar de gate de banco por sistema (tasks 5.1-5.3,
change db-proxy-gate-data-plane).

Um processo por sistema (container próprio, `network_mode: container:<id>`
do sistema — ADR D1) que sobe, para cada conexão Postgres/MySQL do
manifesto, dois listeners de loopback: um pra origem `agente` (MCP/bash,
porta "agent_port") e um pra origem `app` (app gerada, porta "app_port") —
D4, atribuição de origem por listener separado. BigQuery não entra aqui:
é HTTPS, segue direto pelo broker da etapa 3 (Non-Goals do design).

Manifesto (`APPAIFORGE_DB_CONNECTIONS`, uma entrada por conexão, JSON):
    {"name": "...", "kind": "postgres"|"mysql",
     "dsn": "postgresql://user:pass@host:port/db",
     "agent_port": 15400, "app_port": 15401}

As credenciais reais só existem neste env — o container do sistema recebe
só os DSNs de loopback sem usuário/senha (task 5.2).

Uso: SYSTEM_ID=<id> APPAIFORGE_DB_CONNECTIONS='[...]' python3 sidecar.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_proxy  # noqa: E402
import pg_proxy  # noqa: E402
import portal_gate  # noqa: E402

_SERVE = {"postgres": pg_proxy.serve, "mysql": mysql_proxy.serve}
_UPSTREAM_CONFIG = {"postgres": pg_proxy.UpstreamConfig, "mysql": mysql_proxy.UpstreamConfig}


def log(*args) -> None:
    print("[dbproxy-sidecar]", *args, flush=True)


def build_tasks(system_id: str, connections: list[dict], gate_mode: str = "shadow") -> list:
    tasks = []
    for conn in connections:
        kind = conn["kind"]
        if kind not in _SERVE:
            log("kind desconhecido, ignorando conexão:", conn.get("name"), kind)
            continue
        cfg = _UPSTREAM_CONFIG[kind].from_dsn(conn["dsn"])
        serve = _SERVE[kind]
        for origin, port in (("agente", conn["agent_port"]), ("app", conn["app_port"])):
            gate_ctx = portal_gate.GateContext(system_id=system_id, origin=origin, connection_name=conn["name"])
            tasks.append(serve("127.0.0.1", port, cfg, gate_ctx, gate_mode))
    return tasks


async def main_async() -> None:
    system_id = os.environ.get("SYSTEM_ID", "")
    if not system_id:
        print("uso: SYSTEM_ID=<id> APPAIFORGE_DB_CONNECTIONS='[...]' sidecar.py", file=sys.stderr)
        sys.exit(1)
    connections = json.loads(os.environ.get("APPAIFORGE_DB_CONNECTIONS", "[]"))
    gate_mode = os.environ.get("APPAIFORGE_DB_GATE_MODE", "shadow")
    tasks = build_tasks(system_id, connections, gate_mode)
    if not tasks:
        log("nenhuma conexão Postgres/MySQL neste sistema — sidecar ocioso")
        await asyncio.Event().wait()
        return
    log(f"subindo {len(tasks)} listener(s) para {len(connections)} conexão(ões), modo {gate_mode}")
    await asyncio.gather(*tasks)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
