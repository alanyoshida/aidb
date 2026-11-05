# Design

## Context

A etapa 1 (`agent-runtime-profile-and-hardening`, já arquivada) deixou o container do agente rodando como usuário não-root, sem capabilities e sem escalada de privilégio — mas isso é identidade de execução no `docker.containers.run()`, decidida uma vez na criação do container. O confinamento desta etapa é outra camada, decidida pelo próprio processo supervisor (`base-image/afsupervisor/supervisor.py`) em tempo de execução, imediatamente antes do `exec` do agente: seccomp (filtra syscalls) e Landlock (filtra caminhos), ambos auto-impostos e não-privilegiados — nenhum dos dois exige root nem componente externo ao container.

Achados empíricos deste host, verificados nesta sessão antes do design (ver `docs/roadmap-confinamento-do-agente.md`, etapa 2):
- `pyseccomp` (wrapper ctypes sobre `libseccomp`) instala um filtro real e funciona como esperado: syscall negada retorna `-1`/`EPERM`, as demais seguem livres.
- O host expõe Landlock ABI 8 (`/sys/kernel/security/landlock/`, quando montado), e as três syscalls (`landlock_create_ruleset`, `landlock_add_rule`, `landlock_restrict_self`) funcionam neste host via chamada direta (não há binding Python maduro e mantido — ver Decisões).
- O binário do opencode é um executável Bun compilado; o runtime do Bun usa `memfd_create` para a memória JIT do JavaScriptCore compatível com W^X. A alternativa (memory protection keys da CPU, via `BUN_JSC_useJITProtectionKeyUnderSeccompFilter=1`) não está disponível neste host (`grep pku /proc/cpuinfo` vazio). `memfd_create` por isso **não** entra no denylist, ao contrário do esboço inicial do roadmap.
- Mapeamento real de escrita de uma geração completa (task 7.1/7.2 da etapa 1): além de `/workspace`, o agente escreve em `/home/agent/.cache/opencode`, `/home/agent/.cache/uv/*`, `/home/agent/.npm/_cacache`, `/home/agent/.config`, `/home/agent/.local` e em `/tmp` (logs/respostas do padrão de teste da guideline). `writable_paths` do perfil `opencode` em `agent_profiles.py` hoje só lista `/workspace` — incompleto para Landlock sem essa correção.

Ver `proposal.md` para a motivação completa e o que fica fora de escopo (credencial em env var, rootfs somente-leitura, perímetro de rede).

## Goals / Non-Goals

**Goals:**
- Seccomp e Landlock instalados pelo supervisor, derivados do perfil do agente, antes do `exec` do comando do agente.
- Política de caminhos e de syscalls funciona para o perfil `opencode` de hoje sem quebrar nenhum fluxo (geração, checkpoint git, servir a app) e sem exigir binding Python externo para Landlock.
- Resposta explícita e testável para quando o host não suporta Landlock, distinguindo produção (falha fechada) de desenvolvimento (degradação visível).

**Non-Goals:**
- Granularidade por binário dentro do container (ex.: "opencode pode ler a credencial, bash dele não") — Landlock e seccomp são uniformes para toda a árvore de processos; isso exigiria uma ferramenta externa com `fromSource` (KubeArmor) ou BPF-LSM, fora de escopo (etapa 9 do roadmap).
- Rootfs somente-leitura — informada pelo mapa de caminhos desta etapa, mas é a etapa seguinte do roadmap.
- Qualquer alteração no perímetro de rede do agente — etapa 5.
- Calibração fina do `pids_limit` ou de outros limites de recursos — já coberto pela etapa 1.

## Decisions

### Biblioteca para seccomp: `pyseccomp`
Alternativas: escrever o filtro BPF cru (via `ctypes`/`prctl(PR_SET_SECCOMP)` manualmente), ou outra lib Python. `pyseccomp` já foi verificado funcionando neste host nesta sessão, é um wrapper fino e ativamente mantido sobre `libseccomp` (a mesma lib usada pelo runc/Docker), e evita reimplementar a codificação do filtro BPF. Custo: mais uma dependência de sistema (`libseccomp2`) na imagem base.

### Landlock via chamada direta de syscall, não uma lib
Não existe, hoje, um binding Python para Landlock maduro e amplamente mantido (ao contrário de `pyseccomp` para seccomp). A alternativa de depender de um pacote PyPI pouco mantido foi descartada — se ele quebrar ou ficar obsoleto, perdemos a única camada de proteção de caminhos. Em vez disso, um módulo novo e pequeno (`base-image/afsupervisor/sandbox.py`) chama `landlock_create_ruleset`, `landlock_add_rule` e `landlock_restrict_self` via `ctypes.CDLL(None).syscall(...)`, consultando o ABI disponível (`landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)`) para só usar funcionalidades que o host realmente suporta (ex.: regras de porta TCP exigem ABI 4+; este host está em ABI 8). O módulo fica isolado para que, se um binding madurecer depois, a troca seja local.

### Ação do seccomp: `errno`, não `kill`
Alternativas: `SCMP_ACT_KILL_PROCESS` (mata o processo na primeira syscall negada) vs `SCMP_ACT_ERRNO(EPERM)` (a chamada falha, o processo continua). Escolhido `ERRNO`: uma geração que tropeça numa chamada negada (ex.: o agente tenta algo inofensivo mas fora da política) deve poder reportar o erro e seguir, não derrubar a sessão inteira do opencode. Mata o fluxo também seria pior para diagnóstico. Risco aceito: é tecnicamente possível um processo mal-comportado tentar a mesma chamada em loop; nenhuma evidência disso em runs reais até hoje.

### Lista de syscalls negadas por padrão (denylist), não lista de permitidas (allowlist)
Um allowlist exigiria enumerar toda chamada que Bun, opencode, `uv`, `npm`/`node` e as apps geradas precisam — grande, frágil a cada atualização de runtime, e com alto risco de quebrar a geração de forma imprevisível. Um denylist pequeno e justificado (`ptrace`, `bpf`, `mount`, `setns`, `perf_event_open`, `process_vm_readv`/`process_vm_writev`, `unshare(CLONE_NEWUSER)`, `pivot_root`, `io_uring_setup`) é mais fácil de revisar e de justificar syscall por syscall, à custa de não ser uma postura "fail-safe" tão forte quanto um allowlist seria.

### `io_uring_setup` bloqueada
`io_uring` é um vetor conhecido de bypass de seccomp (filtra por número de syscall, não pelas operações que `io_uring` executa por trás) e de escalada de privilégio já exploradas publicamente. Bun tenta `io_uring_setup` mas cai para `epoll` automaticamente quando a chamada falha (`EPERM`/`ENOSYS`) — comportamento verificado via pesquisa nesta sessão, sem necessidade de teste local adicional: é um fallback não-fatal documentado no próprio runtime.

### `memfd_create` permanece fora do denylist
Ver Context — bloquear quebraria o JIT do Bun neste host (sem MPK disponível). Documentado aqui como desvio do esboço original do roadmap, não como omissão.

### Terceiro valor de `ExecutionMode`: `sandboxed`
A etapa 1 criou `ExecutionMode` com `legacy`/`reduced`. Em vez de um flag booleano paralelo ("tem sandbox?"), o confinamento desta etapa se torna um terceiro valor do mesmo enum: `sandboxed` (identidade reduzida da etapa 1 **e** seccomp/Landlock ativos). Isso reaproveita a infraestrutura já existente e testada da etapa 1 — `execution_mode` já é imutável por sistema, já é consultável pelo admin, e `provisioning.py`/`supervisor.py` já ramificam nele. Um flag booleano separado duplicaria essa lógica sem necessidade. Sistemas `reduced` existentes não são retroativamente confinados — migrá-los exigiria recriar o container, fora de escopo aqui (mesma regra de imutabilidade já especificada em `container-lifecycle`).

### Detecção de suporte a Landlock acontece no portal, na criação do sistema — não dentro do container
`ExecutionMode` já é decidido uma vez, na criação do sistema, e fica imutável (spec `container-lifecycle`, etapa 1). A detecção de Landlock precisa acontecer nesse mesmo momento, não depois de o container já estar subindo. Como o container do portal compartilha o kernel do host com os containers de sistema (ambos são containers Docker comuns, não VMs), `provisioning.py` pode chamar a mesma sonda de ABI do módulo `sandbox.py` (`landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)`) diretamente do processo do portal, sem precisar criar um container de teste só para perguntar — é uma chamada de syscall pura, não depende de `securityfs` montado. Alternativa descartada: deferir a detecção para dentro do supervisor e só então decidir o modo — isso violaria "modo fixado na criação", porque o modo já teria sido persistido como `sandboxed` antes de se saber se o host aguenta.

### `require_sandbox`: falha fechada em produção, degradação visível em dev
Mesmo precedente de `storage_opt` em `provisioning.py` (sonda a capacidade, loga aviso, segue sem a funcionalidade, grava `set_status_message` visível ao admin). Um novo setting `require_sandbox: bool = True` (padrão seguro) decide o que `provisioning.py` faz quando a sonda de Landlock reporta ausência de suporte: com `True` (padrão, esperado em produção), a criação do sistema falha explicitamente, nenhum container sobe prometendo um confinamento que não vai ter; com `APPAIFORGE_REQUIRE_SANDBOX=false` (hosts de dev/CI sem Landlock — kernel antigo, Docker-in-Docker sem acesso ao recurso), o sistema nasce em `reduced` em vez de `sandboxed`, com `set_status_message` avisando a degradação. Depois que o modo está persistido, o supervisor dentro do container confia nele: se o modo é `sandboxed`, ele instala Landlock e, na hipótese (não esperada, dado que o portal já sondou o mesmo kernel) de a instalação falhar mesmo assim, trata como falha explícita igual à de perfil ausente (`harness_failed`, agente não sobe) — nunca sobe o agente silenciosamente menos confinado do que o modo promete.

## Risks / Trade-offs

- **Landlock ausente derruba provisionamento em produção por padrão** → mitigado por `require_sandbox=false` ser a válvula de escape explícita para hosts que comprovadamente não suportam; o padrão seguro é intencional (falhar visível é melhor que subir sem a camada esperada e não saber).
- **`writable_paths` do perfil incompleto quebra Landlock silenciosamente (nega escrita que o agente precisa)** → mitigado por já termos o mapa real de escrita da etapa 1 (task 7.2) incorporado ao perfil nesta etapa, e por task de verificação com geração real antes de arquivar.
- **ABI do Landlock varia por host (kernels mais antigos suportam menos regras)** → mitigado por consultar o ABI disponível em runtime e só aplicar regras que o ABI local suporta, em vez de assumir a versão observada neste host.
- **`pyseccomp` como dependência de sistema nova na imagem base** → mitigado por já ter sido testado funcionando nesta sessão; risco residual é só de manutenção (nova dependência para manter atualizada).
- **Denylist de syscalls pode ficar desatualizado conforme o runtime do agente evolui (nova versão do Bun usa uma syscall nova negada)** → mitigado por task de verificação com geração real antes de arquivar, mas é um risco contínuo — cada troca de versão do agente de base pode exigir revisão do denylist. Não há mitigação estrutural além de monitorar falhas.
- **Chamada direta de syscalls Landlock via `ctypes` sem lib dedicada** → mais código para manter correto (números de syscall por arquitetura, construção das structs) do que usar uma lib pronta; aceito porque não há lib madura disponível (ver Decisões) e o volume de código é pequeno (três chamadas).

## Migration Plan

- Sem migração de dados: `ExecutionMode.sandboxed` é só mais um valor do enum já existente; sistemas atuais em `reduced`/`legacy` continuam exatamente como estão (imutabilidade de modo já garantida pela etapa 1).
- Sistemas novos, em hosts com Landlock disponível e `require_sandbox=true` (padrão), nascem em `sandboxed`. Em hosts sem Landlock e `require_sandbox=false`, nascem em `reduced` com aviso.
- Rollback: como o confinamento é instalado em runtime pelo código do supervisor (não por uma migração de banco irreversível), revertê-lo é reverter o deploy da imagem base para uma versão sem o módulo de sandbox — sistemas já criados como `sandboxed` passam a subir sem a camada na próxima recriação do container, sem exigir nenhuma limpeza de dado.
- Rollout recomendado: validar com geração real (`@llm_real`, mesmo padrão usado na verificação da etapa 1) antes de tornar `sandboxed` o modo padrão de novos sistemas em produção.
