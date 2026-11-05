# Proposal

## Why

A etapa 1 (`agent-runtime-profile-and-hardening`) reduziu o poder do container do agente — usuário não-root, sem capabilities, sem escalada de privilégio — mas isso é identidade de execução, não confinamento: dentro do container, o processo do agente ainda pode ler qualquer arquivo que o usuário `agent` alcance, escrever fora do workspace, e chamar qualquer syscall que esse usuário tenha permissão de chamar. Hoje nada impede o agente de escrever fora de `/workspace`, abrir `/proc/1/mem`, ou chamar `ptrace`/`unshare`/`bpf` — o único limite é a identidade do usuário, não o que ele pode fazer com ela.

Esta é a etapa 2 do roadmap de confinamento ([`docs/roadmap-confinamento-do-agente.md`](../../../docs/roadmap-confinamento-do-agente.md)): o supervisor passa a se auto-restringir com seccomp (filtra syscalls por verbo) e Landlock (filtra acesso a caminho por objeto) antes de dar `exec` no agente — um confinamento auto-imposto, não-privilegiado, herdado por toda a árvore de processos que nascer dali (opencode, bash, scripts que o agente escrever), e irrevogável.

## What Changes

- O `afsupervisor` instala um filtro seccomp e um ruleset Landlock, derivados do perfil do agente (`readable_paths`/`writable_paths`, já declarados em `agent_profiles.py` desde a etapa 1), e só então executa o comando do agente.
- Política de arquivo (Landlock): leitura e escrita liberadas sob `/workspace` e sob o `HOME` do usuário do agente; leitura e execução liberadas em `/usr`, `/lib`, `/opt`, `/opencode-config`; tudo o mais fora desses caminhos fica negado por padrão (Landlock é subtrativo: declarar o que é controlado já nega o resto).
- Política de syscalls (seccomp): nega por padrão um conjunto de chamadas que não servem ao trabalho do agente e que, se permitidas, desarmariam o próprio confinamento ou dariam visibilidade sobre o host — `ptrace`, `bpf`, `mount`, `setns`, `perf_event_open`, `process_vm_readv`/`process_vm_writev`, `unshare` com `CLONE_NEWUSER`, `pivot_root`, `io_uring_setup`; demais syscalls permitidas.
- **Desvio do esboço original do roadmap**: `memfd_create` sai do denylist. Pesquisa durante o design encontrou que o runtime do opencode (binário Bun compilado) usa `memfd_create` para memória de JIT compatível com W^X, e a alternativa (memory protection keys da CPU) não está disponível neste host — bloquear quebraria a execução do próprio agente. Registrado como decisão, não esquecimento.
- Modo de execução ganha uma terceira opção além de `legacy`/`reduced`: o confinamento depende do Landlock estar disponível no kernel do host, e a plataforma precisa de uma resposta explícita para quando não está (comportamento de falha fechada em produção, degradação visível em dev — mesmo precedente do `storage_opt` em `provisioning.py`).
- Nenhuma mudança visível no chat, na geração de apps ou no gate de destrutivas: esta etapa é inteiramente dentro do container do sistema, sob o supervisor.

Explicitamente **fora de escopo** (etapas seguintes do roadmap): a credencial do provedor de LLM continua em env var dentro do `opencode.json` — Landlock é uniforme na árvore de processos, então não distingue "o opencode pode ler o config, o bash dele não" (isso é regra por binário, que exige `fromSource` de uma ferramenta externa como KubeArmor, ou BPF-LSM — etapa 9). Rootfs somente-leitura segue fora, informada pelo mapa de caminhos que esta mudança observa na prática. Perímetro de rede (bloquear o agente de alcançar qualquer coisa fora do gate) é a etapa 5.

## Capabilities

### New Capabilities
- `agent-sandbox`: confina o processo do agente e tudo que ele executa a um conjunto de caminhos e syscalls declarados no perfil do agente, auto-imposto pelo supervisor antes de iniciar o agente, sem depender de nenhum componente externo ou privilégio no host

## Impact

- `base-image/afsupervisor/supervisor.py`: instala seccomp e Landlock a partir do perfil, antes de `start_harness()`
- `base-image/afsupervisor/` (novo módulo): construção do filtro seccomp e do ruleset Landlock
- `base-image/Dockerfile`: adiciona `pyseccomp` às dependências Python da imagem
- `portal/appaiforge/agent_profiles.py`: perfil ganha o conjunto de syscalls permitidas/negadas (ou usa um denylist padrão da plataforma, decisão em design.md)
- `portal/appaiforge/models.py` + migração: flag de confinamento disponível/indisponível por sistema (ou reaproveita `execution_mode`, decisão em design.md)
- `portal/appaiforge/provisioning.py`: decide o comportamento quando o host não suporta Landlock
- Testes: marker novo `sandbox`, opt-in (CI pode não ter Landlock), ao lado de `llm_real`
- Sem mudança de API, de UI, ou de dependência do produto (dependência nova é só da imagem base)
