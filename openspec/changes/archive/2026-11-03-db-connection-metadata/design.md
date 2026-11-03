# Design

## Context

Ver `proposal.md — Why`. Estado atual relevante:

- `write_opencode_config()` gera entradas MCP como `mcp[conn_name] = {"type": "local", "command": [...], "enabled": True}` — sem descrição ou contexto.
- O MCP server recebe a URL como argumento posicional (`sys.argv[1]`) e não tem noção de modo de acesso.
- O gate de destrutivas (`is_read_only`) já existe e é usado no MCP server — enforçar `read_only` por conexão é estender o comportamento existente, não reimplementar.
- `_to_safe()` hoje retorna `id, name, kind, host, port, database, username` — `description` e `access_mode` precisam entrar aqui.

## Goals / Non-Goals

**Goals:**
- Contexto da conexão visível ao agente via nome/descrição da ferramenta MCP.
- Enforcement de `read_only` no MCP server por conexão.
- Campos opcionais: compatibilidade total com conexões existentes.

**Non-Goals:**
- Não altera o comportamento do gate de bash (só MCP).
- Não adiciona controle de acesso por usuário à conexão.

## Decisions

### D1. Descrição no nome da ferramenta MCP, não em campo separado

O opencode exibe o nome da ferramenta MCP ao agente. Concatenar `description` ao nome gera contexto imediato sem depender de suporte a campo `description` no formato de config do opencode:

```python
tool_name = conn_name
if conn.description:
    tool_name = f"{conn_name} [{conn.description}]"
if conn.access_mode == "read_only":
    tool_name = f"{tool_name} (somente-leitura)"
```

**Alternativa**: campo `description` no JSON do MCP. Depende do opencode expor esse campo ao agente — não garantido na versão pinada (1.19.x).

### D2. access_mode passado como argumento ao MCP server

O mcp_server.py recebe `access_mode` como segundo argumento:
```
python mcp_server.py <DATABASE_URL> [read_only]
```
Se `read_only` estiver presente, o server rejeita qualquer SQL que não seja leitura — comportamento já implementado globalmente, agora configurável por conexão.

### D3. access_mode default = read_write

Sistemas existentes não mudam de comportamento. Nenhuma migration destrutiva.

## Migration Plan

1. Migration Alembic: `ADD COLUMN description VARCHAR(500) NULLABLE`, `ADD COLUMN access_mode VARCHAR(20) DEFAULT 'read_write'`.
2. Atualizar `register_connection` / `update_connection` para aceitar os novos campos.
3. Atualizar `_to_safe()` para incluir `description` e `access_mode`.
4. Atualizar `write_opencode_config` para usar tool_name composto e passar `access_mode` como arg.
5. Atualizar `mcp_server.py` para ler `sys.argv[2]` e enforçar `read_only` quando presente.
6. Atualizar UI (dialogs de criar/editar conexão).
7. Rollback: reverter migration e código; os campos são opcionais, não há dado crítico a perder.
