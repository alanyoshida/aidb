# Proposal

## Why

O agente recebe as conexões do sistema apenas pelo nome (ex: "vendas", "fiscal"), sem contexto sobre o que cada banco representa, se é produção ou staging, ou se deve ser tratado como somente-leitura. O editor precisa repetir esse contexto em cada prompt. Adicionar metadados estruturados às conexões permite que o agente tome decisões melhores por padrão — sem instrução manual — e que o portal possa enforçar o modo de acesso no MCP server.

## What Changes

- `DbConnection` ganha dois campos opcionais: `description` (texto livre para o agente, ex: "banco de vendas e pedidos") e `access_mode` (`read_write` | `read_only`, padrão `read_write`).
- `write_opencode_config` incorpora description e access_mode no nome/descrição da ferramenta MCP, tornando o contexto visível ao agente sem necessidade de prompt.
- O MCP server enforça `access_mode = read_only`: quando configurado assim, rejeita qualquer SQL de escrita mesmo via bash (hoje o MCP já bloqueia writes; o enforcement passa a ser por conexão, não global).
- A UI de cadastro e edição de conexão expõe os dois campos.

## Capabilities

### New Capabilities

_(nenhuma)_

### Modified Capabilities

- `db-connections`: novos requisitos de metadados de conexão (description e access_mode) e enforcement de acesso somente-leitura.

## Impact

- **Código**: `portal/appaiforge/models.py` (dois campos novos em `DbConnection`); migration Alembic; `portal/appaiforge/services/connections.py` (`register_connection`, `update_connection`, `_to_safe`); `portal/appaiforge/provisioning.py` (`write_opencode_config`); `base-image/gated-mcp/mcp_server.py` (recebe access_mode como argumento); `portal/appaiforge/ui/system_detail.py` (campos na UI).
- **Dados**: migration adiciona `description VARCHAR(500) NULLABLE` e `access_mode VARCHAR(20) DEFAULT 'read_write'` em `db_connections`.
- **Testes**: unit (geração do opencode.json com description/access_mode; enforcement de read_only no MCP); E2E (cadastro com metadados; agente recebe contexto na ferramenta MCP).
- **Compatibilidade**: sistemas existentes recebem `access_mode = read_write` e `description = NULL` por padrão — sem mudança de comportamento.
