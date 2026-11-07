# 0019 — Sandbox do agente: seccomp + Landlock no supervisor

* Status: aceito
* Data: 2026-11-05
* Decidida em: change `agent-sandbox-seccomp-landlock` (capability `agent-sandbox`, etapa 2 do roadmap)
* Relacionada: [0018](0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md), [0013](0013-containers-sempre-ativos-com-reconciliacao.md)
* Estendida por: [0022](0022-confinamento-de-rede-por-porta-tcp-via-landlock.md) (Landlock de rede, por cima do de filesystem aqui)

## Contexto

A etapa 1 ([ADR 0018](0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md)) deixou o agente sem-confinamento real: processo semi-confiável com shell, exposto a prompt injection, dono do workspace. O host de desenvolvimento tem Landlock (ABI 8) e `CONFIG_CGROUP_BPF`, mas **não** tem `bpf` na lista de LSMs ativos — BPF-LSM exigiria `lsm=...,bpf` no cmdline do GRUB + reboot, e um agente privilegiado no host (Tetragon/KubeArmor) contraria o eixo da arquitetura: zero componente novo privilegiado.

Esta é a etapa 2 de [`docs/roadmap-confinamento-do-agente.md`](../roadmap-confinamento-do-agente.md).

## Decisão

**O supervisor instala seccomp + Landlock no processo do agente antes do `exec`.** A instalação roda no **filho**, via `preexec_fn` do `subprocess.Popen` — nunca no próprio supervisor (PID 1), que precisa continuar livre para gerenciar a app depois; restringir o pai o prenderia à política pensada só para o agente. Tudo que nasce dali (opencode, bash, python, script escrito pelo agente) herda as restrições, que são irrevogáveis.

**seccomp filtra verbos; Landlock filtra objetos.** seccomp (programa cBPF clássico) vê número da syscall e argumentos crus — nunca dereferencia ponteiros, logo não faz política por caminho. Landlock (LSM auto-imposto, sem privilégio) declara direitos e concede caminhos via *file descriptors* (imune a corrida de symlink), cobrindo filesystem e porta TCP. Implementação em Python (`pyseccomp` + `ctypes` para as 3 syscalls de Landlock), sem toolchain novo; upgrade path é um shim Rust (`landlock` + `seccompiler`).

**Política dirigida pelo perfil** (ADR 0018): `readable_paths`/`writable_paths` declarados no perfil do agente. Mapa observado em geração real: rw em `/workspace`, caches do agente (`~/.cache`, `~/.npm`, `~/.config`, `~/.local`) e `/tmp`; leitura em `/usr`, `/lib`, `/opt`, `/proc`, `/etc`, `/dev` e `/opencode-config`. Denylist de syscalls: `bpf`, `ptrace`, `mount`, `setns`, `perf_event_open`, `process_vm_readv/writev`, `unshare(CLONE_NEWUSER)`, `io_uring_setup`, `pivot_root`. Apenas `AF_UNIX`, `AF_NETLINK` (proto 0) e `AF_INET`.

**`memfd_create` fica fora do denylist**: o binário do opencode é um executável Bun (~214 MB) cujo JavaScriptCore usa `memfd_create` para JIT compatível com W^X; a alternativa (memory protection keys) não existe neste host. Em contraste, `io_uring_setup` é seguro de bloquear — Bun cai para epoll automaticamente quando a chamada retorna `EPERM`.

**Modo de execução `sandboxed`, fail-closed por padrão.** Terceiro valor de `execution_mode` (ao lado de `legacy`/`reduced`), fixado na criação do sistema por uma sonda de Landlock feita pelo próprio processo do portal. Com `APPAIFORGE_REQUIRE_SANDBOX=true` (padrão), host sem Landlock **recusa** criar o sistema; em dev/CI a flag desligada degrada para `reduced` com aviso visível — mesmo precedente do `storage_opt` ([ADR 0013](0013-containers-sempre-ativos-com-reconciliacao.md)).

## Alternativas consideradas

- **eBPF / BPF-LSM** — mais forte (regra por binário, egress por IP, auditoria), mas exige reboot do host de dev e agente privilegiado; sobrevive mal em k8s gerenciado (etapa 8). Fica para a etapa 9, com AppArmor como backend alternativo a medir antes.
- **Supervisor se auto-restringir antes do exec** — prende o PID 1 à política do agente; qualquer caminho que ele precise tocar depois quebraria o container inteiro. Descartada durante a implementação em favor do `preexec_fn`.
- **KubeArmor `fromSource`** — regra por binário é exatamente o que Landlock não dá; exige o LSM que o host não tem. Etapa 9.
- **Não confinar, só auditar** — não atende o objetivo do roadmap; auditoria sem negação é detecção, não contenção.

## Consequências

- O agente não escreve fora de `/workspace` + caches declarados, não escala privilégio e não toca as syscalls da denylist — herdado por toda a árvore de processos, irrevogável.
- Credenciais de LLM e de banco continuam legíveis via `/proc/self/environ` — removê-las é a etapa 3 (broker de inferência) e a etapa 4 (proxy de banco), não esta change.
- Regra **por binário** ("só o psql abre socket") segue indisponível sem BPF-LSM/AppArmor — etapa 9.
- Landlock só autoriza caminhos com inode no primeiro boot: o aplicador cria `writable_paths` ausentes antes de declarar as regras (achado de verificação real).
- Testes que afirmam **negação** (escrever fora do workspace falha, `unshare -U` falha, `/proc/1/mem` falha) usam marker opt-in `sandbox`: CI pode não ter Landlock.
