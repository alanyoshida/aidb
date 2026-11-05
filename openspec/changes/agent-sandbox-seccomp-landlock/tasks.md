# Tasks

## 1. Dependências da imagem base

- [ ] 1.1 Adicionar `libseccomp2`/`libseccomp-dev` (build) e o pacote `pyseccomp` às dependências de `base-image/Dockerfile`; verificar que `docker build` conclui e que `python -c "import seccomp"` funciona dentro de um container da imagem resultante

## 2. Módulo de sandbox (seccomp + Landlock)

- [ ] 2.1 Criar `base-image/afsupervisor/sandbox.py` com `build_seccomp_filter(deny_syscalls: list[str]) -> SyscallFilter` usando `pyseccomp`, ação padrão `ALLOW` e `SCMP_ACT_ERRNO(EPERM)` para cada syscall do denylist; teste unitário verifica que o filtro construído contém exatamente as regras esperadas, sem precisar carregá-lo (`.load()`) no processo de teste
- [ ] 2.2 Em `sandbox.py`, adicionar `landlock_abi() -> int` (chama `landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)` via `ctypes`, devolve a versão ou 0 quando a syscall não existe/falha) e `apply_landlock(readable_paths: list[str], writable_paths: list[str]) -> None` (cria o ruleset, adiciria regras de leitura/execução para `readable_paths` e leitura/escrita para `writable_paths`, chama `landlock_restrict_self`); marcador de teste `sandbox` (opt-in, pode faltar no host de CI) verifica num host real que escrita fora dos caminhos liberados falha e dentro funciona
- [ ] 2.3 Adicionar `apply_sandbox(profile: dict, deny_syscalls: list[str]) -> None` que chama `build_seccomp_filter` + `.load()` e depois `apply_landlock` a partir de `profile["readable_paths"]`/`profile["writable_paths"]`, na ordem (seccomp antes de Landlock, já que Landlock não precisa de syscalls do denylist); teste unitário com perfil fake confirma que ambos são chamados com os caminhos corretos

## 3. Perfil do agente e denylist de syscalls

- [ ] 3.1 Atualizar `writable_paths` do perfil `opencode` em `portal/appaiforge/agent_profiles.py` para incluir `/home/agent/.cache/opencode`, `/home/agent/.cache/uv`, `/home/agent/.npm`, `/home/agent/.config`, `/home/agent/.local` e `/tmp`, além de `/workspace`, conforme o mapa real de escrita observado na etapa 1 (`docs/roadmap-confinamento-do-agente.md`); verificar com teste unitário que a lista contém cada caminho esperado
- [ ] 3.2 Adicionar constante `DEFAULT_DENY_SYSCALLS` em `agent_profiles.py` (ou módulo dedicado) com `ptrace`, `bpf`, `mount`, `setns`, `perf_event_open`, `process_vm_readv`, `process_vm_writev`, `unshare`, `pivot_root`, `io_uring_setup`; confirmar que `memfd_create` não está na lista (teste unitário que afirma a ausência, documentando a decisão) e que `unshare` é tratado com a restrição a `CLONE_NEWUSER` descrita no design, não um bloqueio total da chamada

## 4. Modo de execução e configuração

- [ ] 4.1 Adicionar `ExecutionMode.sandboxed` em `portal/appaiforge/models.py`; criar migração Alembic encadeada ao head atual; verificar `alembic upgrade head` aplica sem erro e `alembic heads` mostra uma única head
- [ ] 4.2 Adicionar `require_sandbox: bool = True` em `portal/appaiforge/config.py`; verificar que `Settings()` carrega com o padrão `True` e que `APPAIFORGE_REQUIRE_SANDBOX=false` o sobrescreve

## 5. Detecção de suporte e decisão do modo na criação do sistema

- [ ] 5.1 Em `provisioning.py`, antes de criar o container de um sistema novo, sondar `sandbox.landlock_abi()` do próprio processo do portal; quando a sonda reporta suporte, usar `execution_mode=sandboxed`; teste de integração confirma que um sistema novo criado num host com Landlock nasce `sandboxed`
- [ ] 5.2 Quando a sonda reporta ausência de suporte: se `settings.require_sandbox` é `True`, a criação do sistema falha de forma explícita (exceção clara, sistema não é criado); se é `False`, o sistema nasce `reduced` e `set_status_message` grava o aviso de degradação (mesmo padrão já usado para `storage_opt`); testes de integração cobrem os dois ramos com a sonda mockada para "indisponível"

## 6. Supervisor: instalar o sandbox antes do `exec` do agente

- [ ] 6.1 Em `base-image/afsupervisor/supervisor.py`, `start_harness()` passa a chamar `sandbox.apply_sandbox(...)` com o denylist padrão e os caminhos do perfil carregado, antes de `self.runner.spawn(...)`, apenas quando o modo de execução (lido de `AIDB_EXECUTION_MODE` ou equivalente passado pelo `provisioning.py`) é `sandboxed`; teste com `ScriptedHarness`/runner fake confirma que `apply_sandbox` é chamado antes do spawn do comando do agente
- [ ] 6.2 Se o modo é `sandboxed` e `apply_sandbox` lança (Landlock indisponível no container mesmo após a sonda do portal ter indicado suporte), `start_harness()` marca `self.harness_failed = True`, loga a falha em stderr e não sobe o agente — mesmo contrato já usado para perfil ausente/ilegível; teste unitário cobre esse caminho
- [ ] 6.3 Quando o modo é `reduced` ou `legacy`, `start_harness()` sobe o agente sem instalar Landlock (comportamento inalterado da etapa 1); teste de regressão confirma que os testes existentes da etapa 1 para esses modos continuam passando

## 7. Verificação de ponta a ponta com geração real

- [ ] 7.1 Rodar uma geração real (cenário `@llm_real`, fora de CI) num sistema `sandboxed` e verificar ponta a ponta: o agente gera a app, `uv` cria o venv, o checkpoint git é criado, a app responde em `/apps/<slug>`, e nenhuma escrita fora dos `writable_paths` do perfil foi necessária
- [ ] 7.2 Confirmar, na mesma execução, que nenhuma das syscalls do denylist foi necessária ao fluxo normal (sem erros inesperados de `EPERM` nos logs do supervisor/agente) e registrar no roadmap (`docs/roadmap-confinamento-do-agente.md`, etapa 2) a conclusão da verificação

## Workflow follow-up

- Arquivar esta change (`agent-sandbox-seccomp-landlock`) após a revisão do time, sincronizando a spec `agent-sandbox` nas specs principais.
- Avaliar, como entrada da etapa 3 do roadmap (proxy de egress para a credencial do LLM), se a política de caminhos desta etapa precisa de ajuste quando a credencial deixar de estar em `opencode.json`.
