# Proposal

## Why

O `opencode.json` de cada sistema contém as connection strings dos bancos (com senha em plaintext) como argumento do comando MCP, e fica em `/workspace` — o diretório que o agente navega livremente. Em sistemas com múltiplos editors, um editor que não cadastrou as conexões pode pedir ao agente que leia ou liste os arquivos do workspace e obter as senhas dos bancos. Mover o config para fora do workspace elimina esse vetor sem alterar o comportamento do sistema.

## What Changes

- `opencode.json` passa a ser gravado em um diretório de config dedicado fora do workspace (`host_config_dir/<slug>/opencode.json`), bind-mountado no container em `/opencode-config/`.
- O supervisor passa a iniciar `opencode serve` com `cwd=/opencode-config/` em vez de herdar o `WORKDIR` do container (`/workspace`).
- O provisionamento ganha um segundo bind mount por sistema (config dir).
- O workspace (`/workspace`) não contém mais o `opencode.json`.

## Capabilities

### New Capabilities

_(nenhuma — esta mudança não introduz comportamento novo para o usuário)_

### Modified Capabilities

- `db-connections`: novo scenario explícito de que o config do agente (com connection strings) não é acessível no workspace.

## Impact

- **Código**: `portal/appaiforge/provisioning.py` (`write_opencode_config`, `provision_system`); `base-image/afsupervisor/supervisor.py`; `portal/appaiforge/config.py` (nova setting `host_config_dir`).
- **Infra**: containers precisam do bind mount adicional; a imagem base não muda.
- **Testes**: unit test de `write_opencode_config` (verifica path fora do workspace); E2E de conexão não precisa mudar (comportamento visível ao usuário é idêntico).
- **Limitação conhecida**: `DATABASE_URL_*` nas env vars do container ainda expõe senhas via `printenv`. Fechar isso exige container não-root — escopo de change separada.
