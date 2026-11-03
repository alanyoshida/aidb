# Proposal

## Why

O portal suporta apenas PostgreSQL como banco de dados para os sistemas. O campo `kind` já existe no modelo `DbConnection` antecipando extensibilidade, mas a stack inteira (teste de conexão, MCP server, env vars) é hardcoded para Postgres. Adicionar suporte a MySQL amplia os casos de uso sem reescrever a arquitetura existente.

## What Changes

- A UI de cadastro de conexão passa a oferecer seleção do tipo (`PostgreSQL` | `MySQL`).
- `test_connection()` despacha para o driver correto conforme `kind`.
- O MCP server (`gated-mcp/mcp_server.py`) passa a suportar MySQL via driver abstrato (asyncpg para Postgres, aiomysql para MySQL), mantendo as mesmas ferramentas (`list_tables`, `describe_table`, `read_query`).
- `connection_string()` gera o scheme correto (`postgresql://` | `mysql://`).
- `_connection_env()` gera `DATABASE_URL_<NOME>` com o scheme correto por tipo.
- A imagem base (`base-image`) passa a incluir `aiomysql` como dependência adicional.

## Capabilities

### New Capabilities

_(nenhuma)_

### Modified Capabilities

- `db-connections`: requisito de suporte a múltiplos tipos de banco (atualmente apenas PostgreSQL é citado explicitamente como "único tipo suportado no MVP").

## Impact

- **Código**: `base-image/gated-mcp/mcp_server.py` (driver abstrato por kind); `portal/appaiforge/services/connections.py` (`test_connection`, `connection_string`); `portal/appaiforge/ui/system_detail.py` (select de tipo); `portal/appaiforge/provisioning.py` (`_connection_env`).
- **Infra**: `base-image/Dockerfile` adiciona `aiomysql`; rebuild da imagem base necessário.
- **Testes**: unit (test_connection com mock para MySQL); E2E requer MySQL disponível no stack de teste (novo serviço no docker-compose de E2E).
- **Risco**: `information_schema` é padrão SQL e cobre ambos os bancos para `list_tables` / `describe_table`; `read_query` é agnóstico. O maior risco é o driver aiomysql ter comportamento diferente do asyncpg em edge cases de encoding/tipos.
