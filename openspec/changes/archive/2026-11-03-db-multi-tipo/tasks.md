# Tasks

## 1. Imagem base

- [x] 1.1 Adicionar `libmysqlclient-dev` no apt e `aiomysql mysqlclient` no pip em `base-image/Dockerfile`; verificar que `docker build -t appaiforge-base ./base-image` conclui sem erro.

## 2. Serviço — teste e connection string

- [x] 2.1 Refatorar `test_connection` em `connections.py` para receber `kind` e despachar: `psycopg` para `postgres`, `mysqlclient` para `mysql`; atualizar `connection_string` e `_connection_env` para gerar scheme correto por kind; verificar com unit tests que Postgres continua gerando `postgresql://` e MySQL gera `mysql://`, e que `test_connection` chama o driver correto (mock por kind).
- [x] 2.2 Atualizar `register_connection` e `update_connection` para aceitar e persistir `kind`; verificar com unit test que `kind` é salvo e retornado por `_to_safe()`.

## 3. MCP server (base-image)

- [x] 3.1 Refatorar `mcp_server.py` para receber `kind` como segundo argumento e usar `aiomysql` quando `kind == "mysql"`, `asyncpg` caso contrário; substituir `pg_tables` por `information_schema` em `list_tables`; verificar com unit test (mock de asyncpg e aiomysql) que `list_tables` retorna tabelas para ambos os drivers e que escrita é bloqueada em ambos.

## 4. Provisionamento

- [x] 4.1 Atualizar `write_opencode_config` para passar `kind` como argumento ao comando do MCP server de cada conexão; verificar com unit test que o `opencode.json` gerado contém `kind` correto para Postgres e MySQL.

## 5. UI

- [x] 5.1 Adicionar select de tipo (`PostgreSQL` | `MySQL`) no dialog de nova/editar conexão em `ui/system_detail.py`, com porta padrão ajustada por tipo (5432 / 3306); verificar com E2E em `test_systems.py` que uma conexão MySQL pode ser cadastrada (requer serviço mysql no stack E2E — ver follow-up).

## 6. Verificação integrada (Postgres)

- [x] 6.1 Rodar `cd portal && uv run pytest tests/unit tests/bdd` — verdes (sem regressão em Postgres).

## Workflow follow-up

- Adicionar serviço `mysql` ao `docker-compose` do stack E2E e rodar `uv run pytest tests/e2e/test_systems.py` com conexão MySQL.
- Rebuildar imagem base e publicar nova versão pinada.
- Arquivar a change após revisão.
