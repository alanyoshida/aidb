# Tasks

## 1. Settings e diretório de config

- [x] 1.1 Adicionar `host_config_dir: str = "/var/lib/appaiforge/configs"` e `configs_dir: str = "/configs"` em `portal/appaiforge/config.py` (padrão análogo a `host_workspaces_dir`/`workspaces_dir`); verificar que as settings carregam sem erro com `uv run python -c "from appaiforge.config import get_settings; get_settings()"`.

## 2. Provisionamento

- [x] 2.1 Ajustar `write_opencode_config(system, config_dir)` em `provisioning.py` para receber o `config_dir` (fora do workspace) e escrever `opencode.json` lá; verificar com o unit test existente de `write_opencode_config` que o arquivo não é gerado no workspace dir e sim no config dir.
- [x] 2.2 Ajustar `provision_system` para criar `configs_dir/<slug>/` e adicionar o bind mount `host_config_dir/<slug>` → `/opencode-config` (read-only) nas kwargs do container; verificar que o dict `volumes` do container passa a ter dois binds (workspace + config) no unit test de `provision_system`.
- [x] 2.3 Ajustar `refresh_connections` para usar o novo path de config ao chamar `write_opencode_config`; verificar que o unit test de `refresh_connections` passa sem erro.

## 3. Supervisor (base-image)

- [x] 3.1 Ajustar `HARNESS_CMD` ou o `spawn` do opencode em `afsupervisor/supervisor.py` para iniciar com `cwd="/opencode-config"`; verificar via teste do supervisor (ou inspeção do processo iniciado num container de teste) que o opencode é iniciado a partir do diretório `/opencode-config`.

## 4. Verificação de isolamento

- [x] 4.1 Adicionar unit test em `tests/unit/test_opencode_harness.py` (ou `test_connections.py`) verificando que `write_opencode_config` grava em `config_dir` e que o workspace dir resultante **não** contém `opencode.json`; rodar `uv run pytest tests/unit -k opencode_config` — verde.
- [x] 4.2 Rodar suite completa: `cd portal && uv run pytest tests/unit tests/bdd` — verde.

## Workflow follow-up

- Subir stack E2E e rodar `uv run pytest tests/e2e/test_systems.py` para confirmar que conexões continuam funcionando com a nova estrutura de mounts.
- Rebuildar a imagem base se o supervisor mudou: `docker build -t appaiforge-base ./base-image`.
- Arquivar a change após revisão.
