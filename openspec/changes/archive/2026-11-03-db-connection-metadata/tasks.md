# Tasks

## 1. Modelo e migration

- [x] 1.1 Adicionar `description: Mapped[str | None]` (nullable) e `access_mode: Mapped[str]` (default `"read_write"`) em `DbConnection` em `models.py`; criar migration Alembic e verificar com `alembic upgrade head --sql` que os dois campos aparecem na tabela.

## 2. Serviço

- [x] 2.1 Atualizar `register_connection` e `update_connection` em `connections.py` para aceitar e persistir `description` e `access_mode`; verificar com unit test que os campos são salvos e retornados por `_to_safe()` sem expor senha.

## 3. Provisionamento

- [x] 3.1 Atualizar `write_opencode_config` em `provisioning.py` para compor o nome da ferramenta MCP com `description` e indicador de `read_only` quando presentes, e passar `access_mode` como segundo argumento ao comando do MCP server; verificar com unit test que o `opencode.json` gerado contém o nome composto e o argumento correto para uma conexão `read_only` com descrição.

## 4. MCP server (base-image)

- [x] 4.1 Atualizar `mcp_server.py` para ler `sys.argv[2]` como `access_mode` e, quando `"read_only"`, rejeitar toda query que não passe em `is_read_only()`; verificar com unit test do mcp_server que INSERT/UPDATE/DELETE são recusados no modo `read_only` e SELECT passa normalmente.

## 5. UI

- [x] 5.1 Adicionar campos `description` (input opcional) e `access_mode` (select `read_write` / `read_only`) nos dialogs de criar e editar conexão em `ui/system_detail.py`; verificar com E2E em `test_systems.py` que uma conexão cadastrada com `read_only` exibe o modo na listagem.

## 6. Verificação integrada

- [x] 6.1 Rodar `cd portal && uv run pytest tests/unit tests/bdd` — verdes.

## Workflow follow-up

- Subir stack E2E e confirmar que o nome composto aparece nas ferramentas do agente (via opencode.json gerado no container).
- Arquivar a change após revisão.
