"""Entrypoint do sidecar do proxy HTTP(S) de saída (change
`agent-https-forward-proxy`). Um processo por sistema (container próprio,
`network_mode: container:<id>` do sistema — mesmo padrão do `dbproxy` da
etapa 4), subindo sempre, com a allow-list calculada pelo portal entregue
por env — este processo não decide a allow-list, só aplica.

Uso: LISTEN_PORT=<porta> ALLOWED_HOSTS='[["host",porta],...]' python3 sidecar.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proxy import AllowList, serve  # noqa: E402


def log(*args) -> None:
    print("[httpsproxy-sidecar]", *args, flush=True)


def allow_list_from_env() -> AllowList:
    pairs = json.loads(os.environ.get("ALLOWED_HOSTS", "[]"))
    return AllowList.from_pairs([(host, int(p)) for host, p in pairs])


def port_from_env() -> int:
    return int(os.environ.get("LISTEN_PORT", "15500"))


def main() -> None:
    import asyncio

    asyncio.run(serve("127.0.0.1", port_from_env(), allow_list_from_env(), log=log))


if __name__ == "__main__":
    main()
