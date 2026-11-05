# Tasks

## 1. Dependências da imagem base

- [x] 1.1 Adicionar `libseccomp2`/`libseccomp-dev` (build) e o pacote `pyseccomp` às dependências de `base-image/Dockerfile`; verificar que `docker build` conclui e que `python -c "import pyseccomp"` funciona dentro de um container da imagem resultante (o módulo Python do pacote `pyseccomp` se chama `pyseccomp`, não `seccomp`)

## 2. Módulo de sandbox (seccomp + Landlock)

- [x] 2.1 Criar `base-image/afsupervisor/sandbox.py` com `build_seccomp_filter(deny_syscalls: list[str]) -> SyscallFilter` usando `pyseccomp`, ação padrão `ALLOW` e `SCMP_ACT_ERRNO(EPERM)` para cada syscall do denylist; teste unitário verifica que o filtro construído contém exatamente as regras esperadas, sem precisar carregá-lo (`.load()`) no processo de teste
- [x] 2.2 Em `sandbox.py`, adicionar `landlock_abi() -> int` (chama `landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)` via `ctypes`, devolve a versão ou 0 quando a syscall não existe/falha) e `apply_landlock(readable_paths: list[str], writable_paths: list[str]) -> None` (cria o ruleset, adiciria regras de leitura/execução para `readable_paths` e leitura/escrita para `writable_paths`, chama `landlock_restrict_self`); marcador de teste `sandbox` (opt-in, pode faltar no host de CI) verifica num host real que escrita fora dos caminhos liberados falha e dentro funciona
- [x] 2.3 Adicionar `apply_sandbox(profile: dict, deny_syscalls: list[str]) -> None` que chama `build_seccomp_filter` + `.load()` e depois `apply_landlock` a partir de `profile["readable_paths"]`/`profile["writable_paths"]`, na ordem (seccomp antes de Landlock, já que Landlock não precisa de syscalls do denylist); teste unitário com perfil fake confirma que ambos são chamados com os caminhos corretos

## 3. Perfil do agente e denylist de syscalls

- [x] 3.1 Atualizar `writable_paths` do perfil `opencode` em `portal/appaiforge/agent_profiles.py` para incluir `/home/agent/.cache/opencode`, `/home/agent/.cache/uv`, `/home/agent/.npm`, `/home/agent/.config`, `/home/agent/.local` e `/tmp`, além de `/workspace`, conforme o mapa real de escrita observado na etapa 1 (`docs/roadmap-confinamento-do-agente.md`); verificar com teste unitário que a lista contém cada caminho esperado
- [x] 3.2 Adicionar constante `DEFAULT_DENY_SYSCALLS` em `agent_profiles.py` (ou módulo dedicado) com `ptrace`, `bpf`, `mount`, `setns`, `perf_event_open`, `process_vm_readv`, `process_vm_writev`, `unshare`, `pivot_root`, `io_uring_setup`; confirmar que `memfd_create` não está na lista (teste unitário que afirma a ausência, documentando a decisão) e que `unshare` é tratado com a restrição a `CLONE_NEWUSER` descrita no design, não um bloqueio total da chamada (implementado como `sandbox.DEFAULT_DENY_SYSCALLS`, o "módulo dedicado" da própria opção dada pela task — denylist é padrão de plataforma, não por perfil, conforme design.md)

## 4. Modo de execução e configuração

- [x] 4.1 Adicionar `ExecutionMode.sandboxed` em `portal/appaiforge/models.py`; criar migração Alembic encadeada ao head atual; verificar `alembic upgrade head` aplica sem erro e `alembic heads` mostra uma única head
- [x] 4.2 Adicionar `require_sandbox: bool = True` em `portal/appaiforge/config.py`; verificar que `Settings()` carrega com o padrão `True` e que `APPAIFORGE_REQUIRE_SANDBOX=false` o sobrescreve

## 5. Detecção de suporte e decisão do modo na criação do sistema

- [x] 5.1 Adicionar `decide_execution_mode() -> ExecutionMode` em `provisioning.py`, que sonda `sandbox.landlock_abi()` do próprio processo do portal; quando a sonda reporta suporte, devolve `ExecutionMode.sandboxed`; `services/systems.py::create_system` chama essa função antes de instanciar `System(...)` e usa o resultado como `execution_mode` da linha nova (decidido na criação, nunca em `provision_system`, que só consome o valor já persistido); teste confirma que um sistema novo criado num host com Landlock nasce `sandboxed`. Também exigiu atualizar `_execution_identity` e o gate de `os.chown` em `provision_system` para tratar `sandboxed` igual a `reduced` (não-root) — sem isso, sistemas novos (que agora nascem `sandboxed` por padrão) regrediam para rodar como root. Fora do impacto original do proposal.md: para `provisioning.py` poder importar `afsupervisor.sandbox.landlock_abi` em produção (não só nos testes, que já tinham `pythonpath=["../base-image"]`), `deploy/portal.Dockerfile` passou a copiar `base-image/afsupervisor` e setar `PYTHONPATH`; `build_seccomp_filter` teve o `import pyseccomp` movido para dentro da função para a imagem do portal não precisar de `pyseccomp`/`libseccomp2` (ela nunca instala um filtro seccomp, só sonda Landlock)
- [x] 5.2 Em `decide_execution_mode()`: quando a sonda reporta ausência de suporte, se `settings.require_sandbox` é `True`, levanta uma exceção explícita (`SandboxUnavailable`) e `create_system` não cria a linha do sistema; se é `False`, devolve `ExecutionMode.reduced` e `create_system` grava o aviso de degradação direto no `status_message` da linha nova (mesmo padrão já usado para `storage_opt`); testes cobrem os dois ramos com a sonda mockada para "indisponível"

## 6. Supervisor: instalar o sandbox antes do `exec` do agente

- [x] 6.1 Em `base-image/afsupervisor/supervisor.py`, `start_harness()` passa a chamar `sandbox.apply_sandbox(...)` com o denylist padrão e os caminhos do perfil carregado, antes de `self.runner.spawn(...)`, apenas quando o modo de execução (lido de `AIDB_EXECUTION_MODE`, setado em `provisioning.py`) é `sandboxed`; teste com runner fake confirma que `apply_sandbox` é chamado antes do spawn do comando do agente. Corrigido durante a implementação: o confinamento NÃO é auto-imposto no processo do supervisor em si (isso o deixaria preso à política pensada para o agente, incapaz de continuar gerenciando a app depois) — vai como `preexec_fn` do `subprocess.Popen`, rodando só no processo filho entre o fork e o exec; validado num container real que o filho fica confinado e o supervisor (pai) continua livre
- [x] 6.2 Se o modo é `sandboxed` e `apply_sandbox` lança dentro do `preexec_fn` (Landlock indisponível no container mesmo após a sonda do portal ter indicado suporte), a exceção é propagada pelo próprio `subprocess` de volta a `start_harness()`, que marca `self.harness_failed = True`, loga a falha em stderr e não sobe o agente — mesmo contrato já usado para perfil ausente/ilegível; teste unitário cobre esse caminho
- [x] 6.3 Quando o modo é `reduced` ou `legacy`, `start_harness()` sobe o agente sem instalar Landlock (comportamento inalterado da etapa 1, `preexec_fn=None`); teste de regressão confirma que os testes existentes da etapa 1 para esses modos continuam passando

## 7. Verificação de ponta a ponta com geração real

- [x] 7.1 Rodar uma geração real (cenário `@llm_real`, fora de CI) num sistema `sandboxed` e verificar ponta a ponta: o agente gera a app, `uv` cria o venv, o checkpoint git é criado, a app responde em `/apps/<slug>`, e nenhuma escrita fora dos `writable_paths` do perfil foi necessária. Achou e corrigiu 4 lacunas reais nos `readable_paths`/`writable_paths` do perfil (`/proc`, `writable_paths` ausentes no primeiro boot, `/etc`, `/dev` — ver design.md) antes de todos os critérios passarem numa stack e2e isolada com OpenRouter/deepseek real
- [x] 7.2 Confirmar, na mesma execução, que nenhuma das syscalls do denylist foi necessária ao fluxo normal (sem erros inesperados de `EPERM` nos logs do supervisor/agente) e registrar no roadmap (`docs/roadmap-confinamento-do-agente.md`, etapa 2) a conclusão da verificação

## Workflow follow-up

- Arquivar esta change (`agent-sandbox-seccomp-landlock`) após a revisão do time, sincronizando a spec `agent-sandbox` nas specs principais.
- Avaliar, como entrada da etapa 3 do roadmap (proxy de egress para a credencial do LLM), se a política de caminhos desta etapa precisa de ajuste quando a credencial deixar de estar em `opencode.json`.
