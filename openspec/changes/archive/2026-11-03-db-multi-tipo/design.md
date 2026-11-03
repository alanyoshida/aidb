# Design

## Context

Ver `proposal.md — Why`. Estado atual relevante:

- `test_connection()` usa `psycopg.connect()` diretamente — Postgres only.
- `mcp_server.py` usa `asyncpg` e `pg_tables` / `information_schema` — `information_schema` é padrão SQL (cobre MySQL), `pg_tables` não é.
- `connection_string()` gera sempre `postgresql://...`.
- `_connection_env()` gera `DATABASE_URL_<NOME>=postgresql://...`.
- A imagem base não inclui driver MySQL.

## Goals / Non-Goals

**Goals:**
- Suporte a MySQL no cadastro, teste, MCP e env var.
- Mesmas ferramentas MCP (`list_tables`, `describe_table`, `read_query`) para ambos os tipos.
- Sem regressão para conexões PostgreSQL existentes.

**Non-Goals:**
- Não suporta SQLite, MongoDB ou outros tipos neste escopo.
- Não altera o gate de SQL (o classificador `is_read_only` é agnóstico ao dialeto).

## Decisions

### D1. Driver abstrato no MCP server via dicionário de fábricas

```python
# mcp_server.py
async def get_conn(url: str, kind: str):
    if kind == "mysql":
        import aiomysql; return await aiomysql.connect(...)
    return await asyncpg.connect(url)
```

O MCP server recebe `kind` como segundo argumento: `python mcp_server.py <URL> <kind>`.

**Alternativa**: dois MCP servers separados (postgres_mcp.py, mysql_mcp.py). Mais simples de manter, mas dobra o código de boilerplate do FastMCP.

### D2. list_tables via information_schema (padrão SQL)

Substituir `SELECT tablename FROM pg_tables WHERE schemaname = 'public'` por:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')
  AND table_type = 'BASE TABLE'
```
Funciona em Postgres e MySQL. Sem `pg_tables` — sem regressão.

### D3. test_connection despacha por kind

```python
def test_connection(kind: str, host, port, database, username, password):
    if kind == "mysql":
        _test_mysql(host, port, database, username, password)
    else:
        _test_postgres(host, port, database, username, password)
```

`mysqlclient` (síncrono, como psycopg) para o teste de cadastro; `aiomysql` para o MCP server assíncrono.

### D4. connection_string e _connection_env usam scheme por kind

`postgresql://` para postgres, `mysql://` para mysql. A app gerada recebe o scheme correto e usa o driver adequado.

### D5. aiomysql + mysqlclient na imagem base

`pip install aiomysql mysqlclient` no Dockerfile. `mysqlclient` requer `libmysqlclient-dev` no apt.

## Risks / Trade-offs

- **aiomysql encoding/tipos** — comportamento pode diferir do asyncpg em tipos não-padrão (DECIMAL, BLOB). Mitigação: serialização via `default=str` no `json.dumps` já usada no server.
- **Stack E2E precisa de MySQL** — adicionar serviço `mysql` ao docker-compose de E2E aumenta o tempo de setup.
- **mysqlclient requer compilação** — aumenta o tamanho da imagem base; alternativa `pymysql` é pure Python mas mais lento para o teste de conexão.

## Migration Plan

1. Rebuild da imagem base com `aiomysql`, `mysqlclient` e `libmysqlclient-dev`.
2. Ajustar `test_connection` para despachar por kind; ajustar `connection_string` e `_connection_env`.
3. Ajustar `mcp_server.py`: driver abstrato + `list_tables` via `information_schema` + receber `kind` como arg.
4. Ajustar `write_opencode_config` para passar `kind` ao comando do MCP server.
5. UI: select de tipo no dialog de nova/editar conexão.
6. Rollback: regressão zero para Postgres; remover código MySQL e rebuild da imagem.
