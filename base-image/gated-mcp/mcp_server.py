"""MCP server de leitura do AIDB (D2 refinado — spec destructive-gate).

Substitui o server-postgres genérico para as conexões dos sistemas: expõe APENAS
ferramentas de leitura (list_tables, describe_table, read_query) e recusa escritas
com o classificador canônico (sqlgate.py, cópia byte a byte do app_template) —
escritas do agente passam pelo bash com permissionamento do opencode.

Uso: python mcp_server.py "$DATABASE_URL" [kind] [access_mode]  (transport stdio)
kind: "postgres" (padrão), "mysql" ou "bigquery"
access_mode: "read_write" (padrão) ou "read_only"
"""

import asyncio
import base64
import json
import os
import sys
from urllib.parse import parse_qs, urlparse

import asyncpg
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlgate import is_read_only  # noqa: E402  (cópia embarcada do classificador)

DATABASE_URL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL", "")
DB_KIND = sys.argv[2] if len(sys.argv) > 2 else "postgres"
ACCESS_MODE = sys.argv[3] if len(sys.argv) > 3 else "read_write"
if not DATABASE_URL:
    print("uso: mcp_server.py <DATABASE_URL> [kind] [access_mode]", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("appaiforge-read")

_conn = None
_lock = asyncio.Lock()

# --- BigQuery (síncrono via executor) ---

_bq_client_inst = None
_bq_project: str = ""
_bq_dataset: str = ""


def _parse_bq_url(url: str) -> tuple[str, str, str]:
    """Retorna (project, dataset, sa_json) a partir de bigquery://project/dataset?credentials_base64=..."""
    p = urlparse(url)
    project = p.hostname or ""
    dataset = (p.path or "").lstrip("/")
    params = parse_qs(p.query)
    b64 = params.get("credentials_base64", [""])[0]
    # urlsafe_b64decode tolera padding faltante com '=='
    sa_json = base64.urlsafe_b64decode(b64 + "==").decode()
    return project, dataset, sa_json


def _bq_client():
    global _bq_client_inst, _bq_project, _bq_dataset
    if _bq_client_inst is None:
        from google.cloud import bigquery
        from google.oauth2 import service_account

        _bq_project, _bq_dataset, sa_json = _parse_bq_url(DATABASE_URL)
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json),
            scopes=["https://www.googleapis.com/auth/bigquery.readonly"],
        )
        _bq_client_inst = bigquery.Client(project=_bq_project, credentials=creds)
    return _bq_client_inst, _bq_project, _bq_dataset


async def _bq_fetch(sql: str) -> list[dict]:
    loop = asyncio.get_event_loop()

    def _sync():
        client, _, _ = _bq_client()
        rows = client.query(sql).result()
        return [dict(r) for r in rows]

    return await loop.run_in_executor(None, _sync)


# --- Postgres / MySQL ---

def _parse_mysql_url(url: str) -> dict:
    """Extrai componentes de mysql://user:pass@host:port/db"""
    p = urlparse(url)
    return {
        "host": p.hostname or "localhost",
        "port": p.port or 3306,
        "user": p.username or "",
        "password": p.password or "",
        "db": (p.path or "").lstrip("/"),
    }


async def _conn_get():
    global _conn
    async with _lock:
        if DB_KIND == "mysql":
            import aiomysql
            if _conn is None or _conn.closed:
                parts = _parse_mysql_url(DATABASE_URL)
                _conn = await aiomysql.connect(**parts)
        else:
            if _conn is None or _conn.is_closed():
                _conn = await asyncpg.connect(DATABASE_URL)
        return _conn


async def _fetch(sql: str, *args):
    conn = await _conn_get()
    if DB_KIND == "mysql":
        import aiomysql
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args or None)
            return await cur.fetchall()
    else:
        return await conn.fetch(sql, *args)


def _rows_to_json(rows) -> str:
    return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)


# --- MCP tools ---

@mcp.tool()
async def list_tables() -> str:
    """Lista as tabelas do banco."""
    if DB_KIND == "bigquery":
        _, project, dataset = _bq_client()
        rows = await _bq_fetch(
            f"SELECT table_name FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES` "
            "WHERE table_type='BASE TABLE' ORDER BY table_name"
        )
        return _rows_to_json(rows)
    rows = await _fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys') "
        "AND table_type='BASE TABLE' ORDER BY table_name"
    )
    return _rows_to_json(rows)


@mcp.tool()
async def describe_table(table: str) -> str:
    """Descreve as colunas de uma tabela (nome, tipo, nulo, default)."""
    if not table.replace("_", "").isalnum():
        return json.dumps({"error": "nome de tabela inválido"})
    if DB_KIND == "bigquery":
        _, project, dataset = _bq_client()
        rows = await _bq_fetch(
            f"SELECT column_name, data_type, is_nullable, column_default "
            f"FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS` "
            f"WHERE table_name='{table}' ORDER BY ordinal_position"
        )
        return _rows_to_json(rows)
    if DB_KIND == "mysql":
        rows = await _fetch(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name=%s "
            "ORDER BY ordinal_position",
            table,
        )
    else:
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
        msg = "conexão em modo somente-leitura" if ACCESS_MODE == "read_only" else "apenas leitura é permitida via MCP"
        return json.dumps({"error": f"gate: {msg} — {reason}"})
    if DB_KIND == "bigquery":
        rows = await _bq_fetch(sql)
        return _rows_to_json(rows)
    if DB_KIND == "mysql":
        rows = await _fetch(sql)
    else:
        conn = await _conn_get()
        rows = await conn.fetch(sql)
    return _rows_to_json(rows)


if __name__ == "__main__":
    mcp.run(transport="stdio")
