## Why

A exclusão definitiva de um sistema remove container, rota e workspace, mas deixa para trás a pasta de config que o portal grava em `configs_dir/<slug>` (`opencode.json`, `agent-profile.json` e, no perfil `claude-code`, `settings.json`/`mcp-servers.json`). Num ambiente real foram encontradas 15 pastas órfãs, e 224 nas stacks E2E. Além de lixo em disco, um sistema novo criado depois com o mesmo slug encontraria arquivos de config de outro sistema até o primeiro provisionamento.

## What Changes

- `delete_system` passa a remover também `configs_dir/<slug>`, nos dois drivers (no Kubernetes o ConfigMap já era removido junto com o Pod; a pasta local do portal não).
- Arquivar continua preservando a pasta (o reprovisionamento a reescreve de qualquer forma).

## Capabilities

### New Capabilities

_(nenhuma)_

### Modified Capabilities

- `container-lifecycle`: a exclusão definitiva remove também a config do sistema.

## Impact

- `portal/appaiforge/provisioning.py` (`delete_system`).
- Teste de integração `portal/tests/integration/test_provisioning.py`.
- Sem migração: pastas órfãs já existentes não são tocadas por esta change.
