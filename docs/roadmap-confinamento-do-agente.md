# Roadmap — confinamento e política do agente

> **Status**: planejamento aceito, nenhuma etapa implementada.
> **Última revisão**: 2026-11-04.
> Documento de trabalho de longa duração: uma change OpenSpec por etapa, na ordem abaixo.
> Ao concluir uma etapa, marque na tabela e registre o ADR correspondente em
> [`docs/adr/`](adr/README.md).

## Progresso

| # | Etapa | Entregável | Status |
|---|---|---|---|
| 1 | Higiene do container + `AgentProfile` | container não-root, perfil declarativo | ⬜ não iniciada |
| 2 | seccomp + Landlock no `afsupervisor` | agente confinado a `/workspace` | ⬜ não iniciada |
| 3 | Proxy de inferência | chave de LLM fora do container | ⬜ não iniciada |
| 4 | Proxy de banco + gate no data plane | gate independente do agente | ⬜ não iniciada |
| 5 | Perímetro de egress | proxies inescapáveis | ⬜ não iniciada |
| 6 | Telemetria OTel | um trace por execução | ⬜ não iniciada |
| 7 | Segundo agente | validação da arquitetura | ⬜ não iniciada |
| 8 | Kubernetes | pod por sistema | ⬜ não iniciada |
| 9 | KubeArmor / auditoria de kernel (opcional) | regra por binário | ⬜ não iniciada |

---

## Problema

O agente de cada sistema é um **principal semi-confiável com credencial de escrita em
produção** (ADR 0015), shell via bash, e exposto a prompt injection pelo conteúdo das
tabelas que ele lê via MCP. Não é um atacante humano sofisticado: é um LLM imprevisível.

A fronteira de segurança atual é **glob sobre string de comando** em
[`provisioning.py:108`](../portal/appaiforge/provisioning.py) mais extração de SQL por regex em
[`gate.py:88`](../portal/appaiforge/gate.py). Furos conhecidos, sem nenhuma malícia sofisticada:

- `psql -f /tmp/x.sql`, heredoc, `base64 -d | psql`;
- `python -c "import asyncpg; ..."` ou um `.py` que o próprio agente escreve e roda;
- a app NiceGUI gerada, que roda no mesmo container com a mesma credencial — o agente edita
  `dbgate.py` e o gate desaparece;
- credenciais de todas as conexões em **env var** (`DATABASE_URL_<NOME>`) e a chave do
  provedor também — exfiltração é um `curl`;
- a connection string vai na **linha de comando** do MCP server
  ([`provisioning.py:98`](../portal/appaiforge/provisioning.py)), visível em `/proc/*/cmdline`;
- rede: o container está em `appaiforge-net` junto do portal, do Traefik e do **Postgres de
  metadados**, e alcança containers de outros sistemas.

## Decisões já fixadas

1. **Um agente por container.** Sem múltiplos agentes no mesmo container.
2. **Docker local primeiro**, Kubernetes validado depois (etapa 8).
3. **Só opencode no início**, mas a arquitetura pronta para outros agentes (Claude Code,
   Hermes, Kimi, zcode) sem tocar em código de segurança — critério verificado na etapa 7.
4. **Enforcement alugado, decisão construída.** O que é irredutivelmente nosso é a decisão
   semântica com humano no loop (classificar SQL e perguntar no chat), não o mecanismo de
   kernel. Os pontos de enforcement apenas perguntam e obedecem.
5. **O gate pertence ao data plane, não ao control plane.** Ele intercepta a conexão ao banco,
   não o protocolo de permissão do agente.

## Por que não é só "ligar eBPF"

eBPF **não** consegue ser o gate de SQL: decidir "DELETE sem WHERE restritivo" exigiria
remontar o protocolo wire do Postgres com estado, dentro do kernel, e segurar a decisão
esperando aprovação humana. O papel do eBPF é tornar o gate **inescapável** e auditar a
verdade — não implementá-lo.

E o bloqueio "limpo" por BPF-LSM **não está disponível** no host de desenvolvimento:

```
$ cat /sys/kernel/security/lsm
lockdown,capability,landlock,yama,apparmor,ima,evm      # sem 'bpf'
$ grep CONFIG_LSM= /boot/config-$(uname -r)
CONFIG_LSM="landlock,lockdown,yama,integrity,apparmor"  # exige lsm=...,bpf + reboot
```

O que **está** disponível hoje, sem reboot e sem daemon privilegiado:

```
kernel 7.0 · BTF presente · cgroup v2 · CONFIG_CGROUP_BPF=y
Landlock ABI 8   (fs, rede TCP por porta, ioctl, escopos — tudo)
```

Daí o desenho: **Landlock + seccomp + proxy forçado**, que é também o que o NVIDIA OpenShell
usa (sem eBPF nenhum: Landlock, seccomp, netns, CONNECT proxy + OPA).

Comparação detalhada de seccomp vs Landlock vs eBPF — e por que o eBPF **não** substitui os dois —
na [etapa 9](#ebpf-substitui-seccomp--landlock-não--e-por-quê).

---

## Etapa 1 — Higiene do container + `AgentProfile`

**Objetivo**: a base que todas as outras etapas leem. Nada de kernel.

**Escopo**
- `AgentProfile` declarativo, com **um** perfil (`opencode`): comando de exec, caminho e
  formato do config, nome da env de credencial, caminhos graváveis/legíveis, porta do harness,
  uid de execução. Consumido pelo `afsupervisor` em vez do `HARNESS_CMD` hardcoded em
  [`supervisor.py:20`](../base-image/afsupervisor/supervisor.py) e por `write_opencode_config`
  ([`provisioning.py:76`](../portal/appaiforge/provisioning.py)).
- `USER` não-root na imagem; `cap_drop: ALL`, `no-new-privileges`, `pids_limit`, rootfs
  `read_only` + tmpfs, nos kwargs de [`provisioning.py:206`](../portal/appaiforge/provisioning.py).

**Por que o perfil aqui**: Landlock (2), seccomp (2), endpoints de proxy (3, 4) e regras
`fromSource` (9) todos leem dele. Se vier depois, as etapas 2 e 3 são refeitas.

**Entrega verificável**: mesma funcionalidade; teste de integração afirma `id` não-root e
`capsh --print` sem capabilities.

**Não resolve ainda**: nenhum confinamento real. Credenciais continuam em env var e o agente
continua lendo `/proc/self/environ`.

**Migração irreversível — a única do roteiro**: os workspaces existentes no host são de root.
Precisa de `chown` na reconciliação, com cuidado para não quebrar o git dos checkpoints.
Fazer nesta etapa, enquanto é barato.

**Specs/ADR**: `container-lifecycle`. ADR 0018 — *um agente por container, com perfil declarativo*.

---

## Etapa 2 — seccomp + Landlock no `afsupervisor`

**Objetivo**: confinar a árvore de processos do agente. Depende do `no-new-privileges` da etapa 1.

**Como funciona** (para quem retomar sem contexto):
- **seccomp** filtra **verbos**: roda um programa BPF clássico antes de cada syscall, vendo o
  número e os 6 argumentos crus. **Não consegue dereferenciar ponteiros**, logo nunca faz
  política por caminho de arquivo — só por syscall e por flags/ints. Instala sem privilégio se
  `PR_SET_NO_NEW_PRIVS` estiver ligado, é herdado por fork/exec e é **irrevogável**.
- **Landlock** filtra **objetos**: é um LSM auto-imposto e não-privilegiado. Declara os direitos
  que passa a controlar (tudo não concedido vira negado), concede de volta "abaixo de" diretórios
  abertos como **file descriptors** (imune a corrida de symlink), e aplica com
  `landlock_restrict_self` — herdado e irrevogável. Cobre filesystem e porta TCP; **não** cobre IP.

**Escopo**: o supervisor instala os dois a partir do profile e **só então** dá `exec`. Tudo que
nascer dali — opencode, bash, python, script que o agente escreveu — herda e não sai.

Política inicial: rw abaixo de `/workspace`; read+execute em `/usr`, `/lib`, `/opt`; negado
`/proc/*/mem` e montagens do host desnecessárias; denylist de syscalls `bpf`, `ptrace`, `mount`,
`setns`, `perf_event_open`, `process_vm_readv/writev`, `unshare(CLONE_NEWUSER)`,
`io_uring_setup`, `memfd_create`, `pivot_root`; só `AF_UNIX`, `AF_NETLINK` (proto 0) e `AF_INET`.

**Implementação**: começar em **Python** (`pyseccomp` + ctypes para as 3 syscalls do Landlock) —
mantém a convenção do repo e não introduz toolchain. Upgrade path: shim compilado em Rust
(crates `landlock` + `seccompiler`), também reusável por agente.

**Decisão de produto**: se o kernel não tiver Landlock, o container sobe? Seguir o precedente do
`storage_opt` em [`provisioning.py:230`](../portal/appaiforge/provisioning.py) — flag de config,
**fail-closed por padrão em produção**, degradar-com-aviso em dev via `set_status_message`.

**Entrega verificável**: testes de integração que afirmam a negação — escrever fora do workspace
falha, `unshare -U` falha, `cat /proc/1/mem` falha, `cat /etc/shadow` falha.

**Não resolve ainda**: **a credencial no `opencode.json`**. O opencode precisa ler o próprio
config e Landlock é **uniforme na árvore** — se o opencode lê, o bash dele lê. As connection
strings nos args do MCP continuam expostas até a etapa 4. Regra por binário ("só o psql abre
socket") exige `fromSource` do KubeArmor ou BPF-LSM — etapa 9.

**Testes**: marker novo e **opt-in** (`sandbox`), ao lado de `llm_real` — CI pode não ter Landlock.

**Specs/ADR**: capacidade nova `agent-sandbox`. ADR 0019.

---

## Etapa 3 — Proxy de inferência (a chave de LLM sai do container)

**Objetivo**: primeira credencial real a sair do container. Mais simples que o banco (HTTP, sem
wire protocol, sem humano no loop) e constrói o componente que a etapa 4 estende.

**Escopo**: LiteLLM como serviço na rede do portal. O portal emite **virtual key por sessão de
chat**; `write_opencode_config` aponta o `baseURL`
([`provisioning.py:124`](../portal/appaiforge/provisioning.py), já parametrizado) para ele, e
`_provider_env` ([`provisioning.py:44`](../portal/appaiforge/provisioning.py)) injeta o token
opaco no lugar da chave real.

**Por que LiteLLM e não escrever**: multi-agente é **multi-dialeto**. opencode fala
OpenAI-compatible; Claude Code fala Anthropic Messages. O LiteLLM expõe os dois — inclusive
`/v1/messages` e `/v1/messages/count_tokens`, repassando `anthropic-beta`/`anthropic-version` —
e traduz entre eles. Com um agente dava para improvisar; com três, não.

**Ganho colateral**: o `_token_count()` com gambiarra por provedor
([`opencode.py:119`](../portal/appaiforge/harness/opencode.py)) morre. Tokens e custo passam a
vir do proxy, normalizados, reforçando o requirement *Visibilidade de uso de tokens*.

**Entrega verificável**: `docker exec <sys> env | grep -i key` mostra só o token de sessão;
revogar a key de uma sessão derruba só aquela sessão.

**Não resolve ainda**: nada impede o agente de chamar `api.z.ai` direto se descobrir o endereço.
O proxy está **configurado**, não **imposto** — etapa 5.

**Specs/ADR**: `llm-provider-keys`. ADR 0020.

---

## Etapa 4 — Proxy de banco e o gate no data plane

**Objetivo**: o gate funciona independente de **como** a SQL foi emitida, e independente de qual
agente está rodando. É a etapa que destrava o multi-agente.

**Escopo**: proxy de wire protocol Postgres/MySQL no mesmo sidecar da etapa 3, guardando as
credenciais reais e injetando-as. O agente recebe DSN de loopback sem senha. O `sqlgate`, o
`gate.evaluate()` ([`gate.py:36`](../portal/appaiforge/gate.py)) e a UI de aprovação do chat
ficam **intactos** — muda só o gatilho. O `reply_gate`
([`base.py:50`](../portal/appaiforge/harness/base.py)) **sai** do `HarnessPort`.

**Faça em dois passos dentro da etapa** — é aqui que se quebra o produto:
1. **Modo sombra**: intercepta, classifica, audita e **deixa passar tudo**. Roda uma semana
   comparando o que o gate atual pegaria com o que o proxy pega. Mede falso-positivo antes de bloquear.
2. **Modo enforcing** atrás de flag, mantendo os globs de `permission.bash` como
   cinto-e-suspensório. Depois apaga os globs.

**Atribuição de origem**: listener separado por uid (agente vs app gerada), mapeando direto no
campo `origin` que o `GateDecision` já tem.

**BigQuery fica fora**: é HTTPS, vai pelo caminho HTTP da etapa 3, não pelo wire proxy.

**Build vs buy**: não existe pronto — nada no mercado segura uma query esperando aprovação
humana no chat de um produto. Construir sobre primitivas: `pg-proto` (Rust) ou asyncio puro em
Python; parsing de `Q` (simple query) e `P` (Parse) é pequeno. MySQL: `COM_QUERY`.

**Entrega verificável**: teste de aceitação com um caso que hoje passa pelos globs
(`psql -f arquivo.sql`) e que depois é bloqueado.

**Não resolve ainda**: contornável por quem descobrir o endereço real do banco — etapa 5.

**Specs/ADR**: reescrita do `destructive-gate`. O requirement sai de *"interceptar os pedidos de
permissão do harness"* (que assa o mecanismo do opencode dentro da spec) para *"toda conexão a
um banco cadastrado"*, implementável para qualquer agente, inclusive um sem protocolo de
permissão. ADR 0021.

---

## Etapa 5 — Perímetro: tornar os proxies inescapáveis

**Objetivo**: fechar o bypass das etapas 3 e 4, **em Docker local, sem privilégio nenhum**,
reusando o Landlock da etapa 2.

**O truque**: o sidecar do gate compartilha o network namespace do container do agente
(`network_mode: container:<id>`), então os dois veem o mesmo loopback. O proxy escuta em portas
próprias (ex.: 15432, 13306, 18080). O Landlock do agente usa `LANDLOCK_ACCESS_NET_CONNECT_TCP`
(ABI 4+; o host está em ABI 8) para permitir **só** essas portas, negando 5432/3306/443 em geral.
`BIND_TCP` liberado só em 8080 (app) e 4096 (harness).

Funciona porque **Landlock é por árvore de processos, não por namespace**: o agente está
confinado; o processo do proxy, no outro container, não.

HTTP(S) geral (`pip`, `npm`, `uv`): forçar `HTTP_PROXY`/`HTTPS_PROXY` e negar a 443. Ferramenta
que ignora proxy env simplesmente falha — fail-closed, aceitável.

**Spike obrigatório antes de comprometer**: confirmar que as regras de rede do Landlock se
aplicam a conexões de **loopback** (são só por porta, agnósticas de endereço — mas isso é
load-bearing aqui).

**Entrega verificável**: o agente não alcança nada além das portas do gate. Sem eBPF, sem
iptables, sem daemon privilegiado, sem reboot.

**Não resolve ainda**: exfiltração **pelo prompt** — o endpoint do LLM é legítimo e o agente pode
mandar conteúdo do workspace por ele. Irredutível; o próprio OpenShell admite o mesmo limite.

**Specs/ADR**: extensão de `agent-sandbox`.

---

## Etapa 6 — Telemetria OTel

**Objetivo**: a chave Debug do chat e a página de auditoria do gate passam a ser **views sobre a
mesma telemetria**, em vez de pipeline próprio.

**Escopo**: span raiz por run no portal (o `run_id` já existe), com filhos:

```
agent.run (portal)
├── llm.request        ← LiteLLM: model, tokens, custo, virtual key
├── tool.bash | tool.edit  ← _normalize() em opencode.py
├── db.query           ← proxy: db.statement sanitizado + classe do gate
└── policy.decision    ← allow | deny | ask, com latência da aprovação humana
```

Collector → Prometheus (ou Mimir) + Tempo + Loki; Grafana em cima.

**Expectativa calibrada**: a correlação é **por atributo** (`run_id`), **não** propagação W3C — o
opencode não repassa `traceparent`. Cada proxy inicia um span filho resolvendo o `run_id` a
partir da identidade da conexão.

**Cuidados**: nada de evento de exec em label do Prometheus (cardinalidade). Eventos de kernel
como OTLP logs são volume sério — filtrar no kernel **e** no collector, retenção curta.

---

## Etapa 7 — Segundo agente (o teste da arquitetura)

**Objetivo**: validar que as etapas 1–6 produziram abstração de verdade.

**Escopo**: perfil `claude-code` — `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` apontando para
`/v1/messages` do LiteLLM, novo `HarnessPort` para o modo headless
(`--output-format stream-json`), caminhos de Landlock ajustados (`~/.claude`), imagem própria.

**Critério de sucesso — negativo**: se adicionar o segundo agente exigir tocar em **qualquer**
código de segurança (proxy, seccomp, Landlock, gate), a abstração falhou. É o único teste
honesto de prontidão para multi-agente.

**Contexto de por que isso importa**: hoje três agentes têm três protocolos de permissão
incompatíveis — opencode usa SSE `permission.asked` + `POST /session/{id}/permissions/{id}`;
Claude Code usa hook `PreToolUse` com `permissionDecision: allow|deny|ask|defer`; os demais são
desconhecidos. E um agente **sem** protocolo de permissão deixaria o gate silenciosamente
inexistente. Por isso o gate foi para o data plane na etapa 4.

**Imagem**: uma imagem por agente, não uma com todos — superfície menor e `allowed_binaries` honesto.
`BASE_IMAGE` já é configurável.

---

## Etapa 8 — Kubernetes

**Objetivo**: mesmo produto, driver k8s. Só depois da arquitetura estável e validada em dois agentes.

**Escopo**: pod por sistema = container do agente + sidecar do gate. O `iptables REDIRECT` em
initContainer com `NET_ADMIN` (padrão Istio/Linkerd/Kuma, com regra `RETURN` por `--uid-owner`
do gate) **substitui** o truque de porta do Landlock — e é mais forte, porque intercepta por IP
também. Roda em EKS/GKE/AKS gerenciados, sem DaemonSet privilegiado. NetworkPolicy default-deny.
PVC no lugar do bind de host. Service por sandbox + Gateway API no lugar do file provider do
Traefik ([`edge.py:89`](../portal/appaiforge/edge.py)).

**Inversão a ter em mente**: BPF-LSM vem **ligado por padrão** no EKS com AL2023 e no Bottlerocket,
e o GKE COS suporta BPF-LSM + AppArmor. O bloqueio por LSM é mais fácil em k8s gerenciado do que
no host de dev.

**Reavaliar o OpenShell aqui** — ver apêndice.

---

## Etapa 9 (opcional) — KubeArmor e auditoria de kernel

**Objetivo**: o que o Landlock não faz — regra **por binário** (`fromSource`: "só `/usr/bin/psql`
pode abrir `/etc/aidb/creds`") — e o stream de eventos de kernel para a trilha de auditoria.

**KubeArmor**: política em YAML simples, LSM-backed (BPF-LSM/AppArmor), roda em k8s **e
standalone**, e seleciona workload por `matchLabels` em **labels arbitrárias de container** — já
emitimos `appaiforge.slug` e `appaiforge.system_id` em
[`provisioning.py:216`](../portal/appaiforge/provisioning.py), então a mesma YAML serve Docker e k8s.
**Limitação**: a seção `network` do `KubeArmorPolicy` só tem `matchProtocols` (tcp/udp/icmp),
**sem IP nem porta** — não substitui allowlist de egress. Há um CRD `KubeArmorNetworkPolicy` com
CIDR/portas, orientado a nós/VMs.

**Tetragon**: melhor como **fonte de auditoria**, não como ferramenta de política — TracingPolicy
é baixo nível e o volume de eventos é mangueira de incêndio. Receiver gRPC comunitário para o
OTel Collector emite um OTLP log record por evento.

**Falco**: só detecção, reação em userspace é racy. Fora.

### eBPF substitui seccomp + Landlock? Não — e por quê

Pergunta recorrente, registrada aqui para não voltar. Duas confusões comuns primeiro:

**"Instalar o eBPF"** — ele já está no kernel (`CONFIG_BPF_SYSCALL=y`, `CONFIG_CGROUP_BPF=y`,
`CONFIG_BPF_LSM=y`, BTF presente). O que falta são duas coisas distintas: (a) `bpf` na lista de
LSMs **ativos**, para escrever hooks de LSM em eBPF — exige cmdline do GRUB + reboot; e (b) um
agente em userspace que carregue os programas (Tetragon, KubeArmor, ou código nosso).

**`seccomp` já é BPF** — roda um programa BPF *clássico* (cBPF) a cada syscall. Não é categoria
diferente de tecnologia; é BPF com modelo de programa restrito, num ponto específico do kernel.

E Landlock e BPF LSM ficam **no mesmo lugar** do kernel — ambos são LSM:

```
processo
   │ syscall
   ▼
┌─────────────────────────────────────────┐
│ seccomp-bpf        (programa cBPF)      │  número da syscall + 6 args crus
└─────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────┐
│ hooks de LSM  (~250 pontos no kernel)   │  objetos já resolvidos pelo kernel
│   ├── Landlock   ← vocabulário fixo     │
│   ├── AppArmor                          │
│   └── BPF LSM    ← programa eBPF nosso  │
└─────────────────────────────────────────┘
   │
   ▼
 VFS / rede / etc.
```

A diferença não é *onde*, é **quem impõe e com que vocabulário**: Landlock tem vocabulário fixo e
curado, configurado pelo **próprio processo** sem privilégio; BPF LSM é **programável**
(`bpf_lsm_file_open`, `bpf_lsm_bprm_check_security`, `bpf_lsm_socket_connect`, retornando
`-EPERM`) e anexado por um **agente privilegiado no host**.

| | seccomp | Landlock | BPF LSM / eBPF |
|---|---|---|---|
| Granularidade | syscall + args escalares | caminho (via fd) + porta TCP | ~250 hooks, estruturas do kernel |
| Lê strings/caminhos? | **não** | sim (inode resolvido) | sim |
| Privilégio para instalar | **nenhum** (com NNP) | **nenhum** | root no host |
| Quem impõe | o processo, de dentro | o processo, de dentro | agente externo, do host |
| Disponível no host de dev | ✅ | ✅ (ABI 8) | ❌ precisa `lsm=...,bpf` + reboot |
| Regra **por binário** | não | **não** (uniforme na árvore) | **sim** |
| Egress por **IP/CIDR** | não | **não** (só porta) | **sim** (+ redirect de destino) |
| Telemetria / auditoria | quase nenhuma | **nenhuma** | **excelente** |
| Política ao vivo, sem recriar container | não | não | **sim** (mapas) |
| k8s gerenciado / Fargate | ✅ | ✅ | ❌ |
| Custo de manutenção | baixo | baixo | alto (drift, verifier, CO-RE) |

**O que só o eBPF dá** — e é por isso que esta etapa existe:
1. **Regra por binário** — Landlock é herdado e uniforme na árvore, então não dá para dizer "o
   opencode lê o config, o bash dele não".
2. **Egress por IP/CIDR** e reescrita de destino (o redirect transparente).
3. **Auditoria** — exec com argv, linhagem de processo, connect, open. Landlock e seccomp são
   mecanismos de *negar*; eles não contam o que aconteceu. Aqui não há alternativa.
4. **Política ao vivo.** Landlock e seccomp são aplicados no `exec` e irrevogáveis: mudar política
   = recriar o container. Isso já dói hoje — `refresh_connections` chama `provision_system`, e a
   spec `agent-harness` tem um requirement inteiro sobre avisar *"Contexto do agente reiniciado"*.

**O que só eles dão**: zero privilégio e zero componente novo no host (o eixo desta arquitetura);
irrevogabilidade herdada por construção; fail-closed antes do `exec`, sem janela; e código
trivial de testar.

**O argumento que decide — eles protegem a camada eBPF.** Se o agente pudesse chamar `bpf()`,
carregaria programas próprios; com `setns`, sairia do cgroup em que a política está ancorada; com
`perf_event_open` e `process_vm_readv`, bisbilhotaria. O denylist de seccomp da etapa 2 bloqueia
exatamente esses. **O seccomp é o que torna uma política eBPF confiável** — a camada de baixo
sustenta a de cima. Não são abordagens concorrentes.

**Decisão: não substituir a etapa 2.** Ela funciona hoje sem reboot e sem componente privilegiado,
é a única das três que sobrevive em k8s gerenciado (etapa 8), e sem ela qualquer política eBPF é
contornável pelo próprio agente.

**Antes de mexer no boot**: para o `fromSource` do KubeArmor talvez não precise de BPF-LSM — o
**AppArmor já está ativo** no host de dev e serve de backend. Medir essa alternativa primeiro.

Se ainda assim quiser habilitar o `bpf`, a pegadinha é que `lsm=` **substitui a lista inteira**,
não acrescenta (escrever só `lsm=bpf` perde AppArmor, Landlock e Yama). A partir do
`CONFIG_LSM` atual do host, e reversível desfazendo o `/etc/default/grub`:

```bash
sudo sed -i 's/^GRUB_CMDLINE_LINUX="\(.*\)"/GRUB_CMDLINE_LINUX="\1 lsm=landlock,lockdown,yama,integrity,apparmor,bpf"/' /etc/default/grub && sudo update-grub
# depois do reboot: cat /sys/kernel/security/lsm   (deve listar 'bpf')
```

---

## Sequenciamento

- **Caminho crítico**: `1 → 2 → 5` (confinamento) e `1 → 3 → 4` (credenciais/gate). A 5 depende
  das duas trilhas.
- **Paralelizável**: 3 e 4 compartilham o sidecar, mas 3 vai sozinha enquanto 4 está em sombra.
  A 6 pode começar junto da 3 (o LiteLLM já emite spans de graça).
- **Primeiro marco demonstrável**: fim da etapa 3 — container sem root, confinado, e sem chave de
  LLM dentro. Três coisas que hoje são o contrário, sem ter mexido no gate.
- **Mapa OpenSpec**: cinco changes (1, 2, 3, 4, 5+6), quatro ADRs novos a partir do 0018, duas
  specs novas (`agent-sandbox`, `agent-policy`), reescrita de `destructive-gate`, ajustes em
  `container-lifecycle` e `llm-provider-keys`.

## Spikes abertos

| # | Pergunta | Bloqueia |
|---|---|---|
| S1 | Regras de rede do Landlock se aplicam a loopback? | Etapa 5 |
| S2 | `pyseccomp` + ctypes dão conta, ou precisa de shim compilado? | Etapa 2 |
| S3 | Qual syscall do denylist quebra o runtime do opencode (Bun/Node)? | Etapa 2 |
| S4 | LiteLLM cobre todos os provedores do catálogo (GLM, OpenRouter, openai-compatible)? | Etapa 3 |
| S5 | Quanto falso-positivo o modo sombra do gate revela? | Etapa 4 |

## Fora de escopo (limites aceitos)

- **Exfiltração pelo prompt**: endpoint de LLM legítimo, conteúdo arbitrário. Irredutível.
- **Scrub de output de aplicação**: credencial em stack trace continua vazando.
- **BPF-LSM no host de dev**: exige `lsm=...,bpf` no cmdline + reboot. Só se sobrar necessidade
  concreta depois de 1–8.
- **eBPF em plataformas gerenciadas**: Fargate, Cloud Run e k8s gerenciado sem DaemonSet
  privilegiado não suportam. Por isso o perímetro é proxy+iptables, que degrada; eBPF é upgrade,
  não alicerce.

---

## Apêndice — NVIDIA OpenShell

Avaliado e **não adotado agora**; reavaliar na etapa 8.

**O que é**: runtime para "fleets of autonomous AI agents", Apache-2.0, **0.1.x**. Política YAML
declarativa em quatro camadas — filesystem, process, network e **inference**. Sem eBPF: usa
Landlock (fs), seccomp (process), netns + CONNECT proxy + OPA (rede), e credencial
**endpoint-bound por placeholder** (o agente nunca vê a chave real). Tem verificação formal que
sinaliza mudanças de política arriscadas. Drivers para Docker/Podman, Kubernetes e MicroVM; o
quickstart deles roda o próprio opencode.

**Por que não agora** — colisões com esta arquitetura:
1. **Rede do workload desabilitada** no driver Docker (tudo brokerado pelo supervisor), mas temos
   **três caminhos de entrada sempre-ligados**: Traefik → `:8080`
   ([`edge.py:30`](../portal/appaiforge/edge.py)), portal → `:4096`
   ([`agent_queue.py:475`](../portal/appaiforge/agent_queue.py)) e a sonda de saúde
   ([`health_monitor.py:81`](../portal/appaiforge/health_monitor.py)). A doc deles diz que a
   exposição de porta via CLI é para sessões curtas e *"unreliable"* para always-on
   (issue #994). No driver k8s há caminho real (Service por sandbox + Gateway API).
2. **PID 1**: o entrypoint da imagem é substituído pelo supervisor deles (comando via `-- <cmd>`),
   colidindo com o ADR 0003.
3. **Workspace**: mounts de host nos drivers Docker/Podman têm `read_only: true` por padrão
   (issue #500 em aberto); no k8s o `/sandbox` é PVC.
4. **Dono do ciclo de vida**: o Gateway deles quer coordenar lifecycle; nós já temos isso em
   `provisioning.py` + reconciliação + limites + labels. Adotar é **reescrever** `provisioning.py`,
   não adicionar camada.
5. **Não resolve o gate de SQL**: endpoints `protocol: tcp` "apply no request rules" — sem
   inspeção L7 nem rewriting de credencial dentro do stream. Família HTTP tem L7 completo
   (e é MITM com CA própria; `tls: skip` desliga o rewriting).

**O que vale roubar já**: o desenho das etapas 2, 3 e 5 é o mesmo, e o denylist de seccomp deles
é referência pronta.

## Referências

- [Landlock — kernel.org](https://docs.kernel.org/userspace-api/landlock.html) · [landlock(7)](https://man.archlinux.org/man/landlock.7.en)
- [OpenShell: arquitetura](https://docs.nvidia.com/openshell/about/architecture) · [segurança](https://docs.nvidia.com/openshell/latest/security)
- [Anthropic sandbox-runtime](https://github.com/anthropics/sandbox-runtime) (bubblewrap + proxy com allowlist por SNI)
- [LiteLLM `/v1/messages`](https://docs.litellm.ai/docs/anthropic_unified/) · [virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [KubeArmor: spec de política](https://docs.kubearmor.io/kubearmor/documentation/security_policy_specification) · [matriz de suporte](https://github.com/kubearmor/KubeArmor/blob/main/getting-started/support_matrix.md)
- [Istio Proxy Redirection](https://github.com/istio/istio/wiki/Proxy-Redirection) (padrão do initContainer iptables)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks) · [modo headless](https://docs.claude.com/pt/docs/claude-code/sdk/sdk-headless)
- [pg-proto](https://docs.rs/pg-proto/latest/pg_proto/) (wire protocol Postgres para proxies)
