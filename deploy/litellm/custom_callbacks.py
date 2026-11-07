"""Callback customizado do LiteLLM (comunidade): posta o payload padrão de
cada chamada bem-sucedida para o endpoint interno do portal, que grava o uso
de tokens/custo de forma idempotente (etapa 3, ADR 0020, D6).

O logger HTTP genérico do LiteLLM é Enterprise; este arquivo cumpre o mesmo
papel com um CustomLogger montado via `custom_callback_path`.
"""

import os

import httpx
from litellm.integrations.custom_logger import CustomLogger

_ENDPOINT = os.environ.get("AIDB_USAGE_ENDPOINT", "")
_TOKEN = os.environ.get("AIDB_USAGE_TOKEN", "")
_HEADERS = {"X-AIDB-Broker-Token": _TOKEN} if _TOKEN else {}


class ProxyHandler(CustomLogger):
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        payload = kwargs.get("standard_logging_object")
        if os.environ.get("AIDB_USAGE_DEBUG") and payload:
            meta = payload.get("metadata") or {}
            print(
                "aidb-usage-debug:",
                "keys=", sorted(payload.keys()),
                "| metadata=", {k: v for k, v in meta.items() if isinstance(v, (str, int, float, dict))},
                "| model=", payload.get("model"),
                "| cost=", payload.get("response_cost"),
                flush=True,
            )
        if not payload or not _ENDPOINT:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(_ENDPOINT, json=payload, headers=_HEADERS)
        except Exception:  # noqa: BLE001 - telemetria não pode derrubar a chamada
            pass

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        pass  # falhas de provedor não geram uso a registrar


proxy_handler = ProxyHandler()
