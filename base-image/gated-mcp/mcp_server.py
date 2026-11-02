"""MCP server de leitura do AppAIForge (D2 refinado — spec destructive-gate).

Substitui o server-postgres genérico para as conexões dos sistemas: expõe APENAS
ferramentas de leitura (list_tables, describe_table, read_query) e recusa escritas
com o classificador canônico (sqlgate.py, cópia byte a byte do app_template) —
escritas do agente passam pelo bash com permissionamento do opencode.

Uso: python mcp_server.py "$DATABASE_URL"  (transport stdio)
"""

import asyncio
import json
import os
import sys

import asyncpg
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlgate import is_read_only  # noqa: E402  (cópia embarcada do classificador)

DATABASE_URL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("uso: mcp_server.py <DATABASE_URL>", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("appaiforge-read")

_conn = None
_lock = asyncio.Lock()


async def _conn_get():
    global _conn
    async with _lock:
        if _conn is None or _conn.is_closed():
            _conn = await asyncpg.connect(DATABASE_URL)
        return _conn


def _rows_to_json(rows) -> str:
    return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)


@mcp.tool()
async def list_tables() -> str:
    """Lista as tabelas públicas do banco."""
    conn = await _conn_get()
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    return _rows_to_json(rows)


@mcp.tool()
async def describe_table(table: str) -> str:
    """Descreve as colunas de uma tabela (nome, tipo, nulo, default)."""
    if not table.replace("_", "").isalnum():
        return json.dumps({"error": "nome de tabela inválido"})
    conn = await _conn_get()
    rows = await conn.fetch(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 "
        "ORDER BY ordinal_position",
        table,
    )
    return _rows_to_json(rows)


@mcp.tool()
async def read_query(sql: str) -> str:
    """Executa uma consulta de LEITURA (SELECT/EXPLAIN). Escritas são sempre recusadas."""
    ok, reason = is_read_only(sql)
    if not ok:
        return json.dumps({"error": f"gate: apenas leitura é permitida via MCP — {reason}"})
    conn = await _conn_get()
    rows = await conn.fetch(sql)
    return _rows_to_json(rows)


if __name__ == "__main__":
    mcp.run(transport="stdio")
