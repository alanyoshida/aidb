"""Unitários do mcp_server: access_mode read_only recusa escritas; SELECT passa."""

import asyncio
import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


def _build_module(access_mode: str):
    """Carrega mcp_server com DATABASE_URL e ACCESS_MODE fixos, sem side effects."""
    # Simula os módulos que o server importa
    fake_asyncpg = MagicMock()
    fake_mcp_module = types.ModuleType("mcp")
    fake_server = types.ModuleType("mcp.server")
    fake_fastmcp_mod = types.ModuleType("mcp.server.fastmcp")

    class FakeFastMCP:
        def __init__(self, name):
            self.tools = {}

        def tool(self):
            def decorator(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorator

        def run(self, transport=None):
            pass

    fake_fastmcp_mod.FastMCP = FakeFastMCP
    fake_mcp_module.server = fake_server
    fake_server.fastmcp = fake_fastmcp_mod

    saved_argv = sys.argv[:]
    saved_modules = {}
    for mod in ["asyncpg", "mcp", "mcp.server", "mcp.server.fastmcp"]:
        saved_modules[mod] = sys.modules.get(mod)

    sys.argv = ["mcp_server.py", "postgresql://localhost/test", "postgres", access_mode]
    sys.modules["asyncpg"] = fake_asyncpg
    sys.modules["mcp"] = fake_mcp_module
    sys.modules["mcp.server"] = fake_server
    sys.modules["mcp.server.fastmcp"] = fake_fastmcp_mod

    # Remove cached module if any
    sys.modules.pop("mcp_server", None)

    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "mcp_server",
        os.path.join(os.path.dirname(__file__), "mcp_server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sys.argv = saved_argv
    for key, val in saved_modules.items():
        if val is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = val

    return mod


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_read_only_rejeita_insert():
    mod = _build_module("read_only")
    result = _run(mod.read_query("INSERT INTO t VALUES (1)"))
    import json
    data = json.loads(result)
    assert "error" in data
    assert "somente-leitura" in data["error"]


def test_read_only_rejeita_update():
    mod = _build_module("read_only")
    result = _run(mod.read_query("UPDATE t SET x=1 WHERE id=1"))
    import json
    data = json.loads(result)
    assert "error" in data


def test_read_only_rejeita_delete():
    mod = _build_module("read_only")
    result = _run(mod.read_query("DELETE FROM t WHERE id=1"))
    import json
    data = json.loads(result)
    assert "error" in data


def test_read_only_select_passa():
    mod = _build_module("read_only")
    rows = [{"id": 1}]
    fake_conn = MagicMock()
    fake_conn.is_closed.return_value = False
    fake_conn.fetch = AsyncMock(return_value=rows)
    mod._conn = fake_conn

    import json
    result = _run(mod.read_query("SELECT * FROM t"))
    data = json.loads(result)
    assert "error" not in data or "gate" not in data.get("error", "")


def test_read_write_select_passa():
    mod = _build_module("read_write")
    rows = [{"id": 1}]
    fake_conn = MagicMock()
    fake_conn.is_closed.return_value = False
    fake_conn.fetch = AsyncMock(return_value=rows)
    mod._conn = fake_conn

    import json
    result = _run(mod.read_query("SELECT * FROM t"))
    data = json.loads(result)
    assert "error" not in data or "gate" not in data.get("error", "")


def test_read_write_insert_ainda_bloqueado():
    """Mesmo em read_write o gate de read_query bloqueia escritas."""
    mod = _build_module("read_write")
    import json
    result = _run(mod.read_query("INSERT INTO t VALUES (1)"))
    data = json.loads(result)
    assert "error" in data
