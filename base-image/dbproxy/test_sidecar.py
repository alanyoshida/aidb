"""Unitários do orquestrador do sidecar (task 5.1/5.3) — sem rede real."""

import asyncio

import sidecar


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_build_tasks_cria_dois_listeners_por_conexao(monkeypatch):
    calls = []

    async def fake_serve(host, port, cfg, gate_ctx, gate_mode="shadow"):
        calls.append((host, port, cfg.database, gate_ctx.origin, gate_ctx.connection_name, gate_mode))

    monkeypatch.setitem(sidecar._SERVE, "postgres", fake_serve)
    monkeypatch.setitem(sidecar._SERVE, "mysql", fake_serve)

    connections = [
        {"name": "vendas", "kind": "postgres", "dsn": "postgresql://u:p@h:5432/vendasdb",
         "agent_port": 15400, "app_port": 15401},
        {"name": "legado", "kind": "mysql", "dsn": "mysql://u:p@h:3306/legadodb",
         "agent_port": 15402, "app_port": 15403},
    ]
    tasks = sidecar.build_tasks("sys-1", connections, "enforce")
    assert len(tasks) == 4

    async def go():
        await asyncio.gather(*tasks)

    _run(go())

    assert ("127.0.0.1", 15400, "vendasdb", "agente", "vendas", "enforce") in calls
    assert ("127.0.0.1", 15401, "vendasdb", "app", "vendas", "enforce") in calls
    assert ("127.0.0.1", 15402, "legadodb", "agente", "legado", "enforce") in calls
    assert ("127.0.0.1", 15403, "legadodb", "app", "legado", "enforce") in calls


def test_build_tasks_ignora_kind_desconhecido():
    connections = [{"name": "bq", "kind": "bigquery", "dsn": "bigquery://x/y", "agent_port": 1, "app_port": 2}]
    assert sidecar.build_tasks("sys-1", connections) == []


def test_build_tasks_sem_conexoes_devolve_lista_vazia():
    assert sidecar.build_tasks("sys-1", []) == []
