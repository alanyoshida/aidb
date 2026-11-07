# Roadmap — confinamento e política do agente

> **Status**: plano aceito; etapas 1–2 concluídas, etapa 3 implementada (verificação real pendente).
> **Última revisão**: 2026-11-04.
> Documento de trabalho de longa duração: uma change OpenSpec por etapa, na ordem abaixo.
> Ao concluir uma etapa, marque na tabela e registre o ADR correspondente em
> [`docs/adr/`](adr/README.md).

## Progresso

| # | Etapa | Entregável | Status |
|---|---|---|---|
| 1 | Higiene do container + `AgentProfile` | container não-root, perfil declarativo | ✅ concluída (change `agent-runtime-profile-and-hardening`, ADR 0018) |
| 2 | seccomp + Landlock no `afsupervisor` | agente confinado a `/workspace` | ✅ concluída (change `agent-sandbox-seccomp-landlock`, capability `agent-sandbox`) |
| 3 | Broker de inferência | nenhuma credencial de LLM no container | ✅ concluída (change `inference-broker`, ADR 0020) |
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

## Etapa 1 — Higiene do container + `AgentProfile` ✅ concluída

**Objetivo**: a base que todas as outras etapas leem. Nada de kernel.

**Entregue** (change `agent-runtime-profile-and-hardening`, ADR 0018 — ver
[`docs/adr/0018-...md`](adr/0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md)):
- Perfil declarativo em `portal/appaiforge/agent_profiles.py`, com **um** perfil (`opencode`):
  comando, cwd, caminho do config, porta do harness, caminhos legíveis/graváveis, e o nome da env
  de credencial (literal ou `from_provider`, delegando ao catálogo). Serializado como JSON em
  `configs_dir/<slug>/agent-profile.json` e entregue via `AIDB_AGENT_PROFILE` — único ponto de
  entrada fixo do supervisor, que não embute mais `HARNESS_CMD` nenhum.
- Imagem base com usuário não-root (`agent`, uid/gid 1000) como padrão, opencode relocado para
  fora de `/root`.
- `cap_drop: ALL`, `no-new-privileges` e `pids_limit` nos kwargs do container — **só** no modo de
  execução `reduced`. **Rootfs `read_only` ficou fora**: decisão explícita, deferida para a etapa
  2, porque o cache do opencode (pacotes de provedor baixados em runtime) vive em `HOME`, e medir
  o mapa de escrita antes de tornar o filesystem imutável evita quebrar isso sem necessidade.

**Mudança em relação ao plano original — sem migração, com modo persistido**: a "migração
irreversível" prevista aqui (chown na reconciliação) **não aconteceu**. Decisão explícita do
usuário: só sistemas **novos** usam a identidade reduzida; sistemas existentes continuam como
root, sem nenhuma intervenção. Isso exigiu um campo novo — `execution_mode` (`legacy`/`reduced`)
em `System`, fixado na criação e imutável — porque sem estado persistido a reconciliação não
teria como saber qual container recriar com qual identidade. `legacy` é o `server_default` da
migração (preserva todo sistema existente); `reduced` é o default do modelo (todo sistema novo).

**Entrega verificável**: testes de integração confirmam, nos dois modos, o `user` e `cap_drop`
corretos nos atributos do container e via `id` dentro dele (não foi preciso `capsh` — os
atributos do Docker já expõem `HostConfig.CapDrop` diretamente). Migração Alembic testada ponta a
ponta contra Postgres descartável: uma linha inserida antes da migração vira `legacy` depois do
upgrade; `alembic heads` lista um único head. **Geração real completa verificada** (task 7.1,
2026-11-05, OpenRouter/deepseek numa stack E2E isolada): app gerada, `uv venv` criado, checkpoint
git registrado (com o próprio relato de teste da guideline da etapa 1), app respondendo 200 em
`/apps/<slug>`, todo arquivo do agente com dono uid 1000 — nunca root.

**Achado real durante a verificação, corrigido**: `/opencode-config` chegava **vazio** no
container tanto no stack E2E quanto em produção — nem `docker-compose.yml` nem
`docker-compose.e2e.yml` montavam `/configs` no serviço do portal (só `/workspaces`), então
`write_opencode_config`/`write_agent_profile` escreviam num diretório efêmero da própria imagem
do portal, nunca visível ao container do sistema. Bug pré-existente, introduzido pela change
arquivada `db-config-fora-do-workspace` (2026-11-03), antes do início deste roadmap — não
causado pela etapa 1, mas só descoberto ao tentar rodar opencode de verdade pela primeira vez
desde então. Os dois compose ganharam o mount `/configs` (mesmo padrão de `/workspaces`).

**Não resolve ainda**: nenhum confinamento real de kernel. Credenciais continuam em env var e o
agente continua lendo `/proc/self/environ`. Regra por binário e rootfs imutável ficam para a
etapa 2.

---

## Etapa 2 — seccomp + Landlock no `afsupervisor` ✅ concluída

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

**Mapa de caminhos observado (task 7.2 da etapa 1 — geração real, OpenRouter/deepseek, 2026-11-05)**:
uma geração completa (app + `uv venv` + `py_compile` + teste HTTP com log, seguindo a própria
guideline de teste proativo) tocou, além de `/workspace`, dois caminhos que a política inicial
**não previa**:
- `/home/agent` (HOME): `.cache/opencode`, `.cache/uv`, `.cache/uv/{interpreter,sdists,wheels,simple,archive}-v*`,
  `.npm/_cacache`, `.config`, `.local` — cache do opencode, do `uv` e do `npm`. Sem rw aqui o
  agente não consegue nem resolver o interpretador Python para o venv.
- `/tmp`: a técnica de teste da guideline (`PORT=8099 timeout 15 ... main.py > /tmp/app_test.log
  2>&1 & ... curl -o /tmp/app_resp.html ...`) grava log e resposta HTTP ali. Negar `/tmp` quebra
  exatamente o fluxo de autoteste que a etapa 1 ensinou o agente a seguir.

Política revisada: rw abaixo de `/workspace`, `/home/agent` e `/tmp`; read+execute em `/usr`,
`/lib`, `/opt`, `/opencode-config`; negado `/proc/*/mem` e montagens do host desnecessárias;
denylist de syscalls `bpf`, `ptrace`, `mount`, `setns`, `perf_event_open`,
`process_vm_readv/writev`, `unshare(CLONE_NEWUSER)`, `io_uring_setup`, `pivot_root`; só
`AF_UNIX`, `AF_NETLINK` (proto 0) e `AF_INET`.

**`memfd_create` sai do denylist original — achado de pesquisa, não observação da execução**: o
binário do opencode é um executável Bun compilado (~214 MB, confirmado via `file`/header ELF
neste host). O JavaScriptCore de Bun usa `memfd_create` para memória de JIT compatível com W^X
(mapeamento dual RW→RX); a alternativa (memory protection keys da CPU, via
`BUN_JSC_useJITProtectionKeyUnderSeccompFilter=1`) não está disponível neste host (`grep pku
/proc/cpuinfo` vazio — sem suporte a MPK). Bloquear quebraria o JIT do próprio agente. Em
contraste, `io_uring_setup` **é seguro de bloquear**: Bun tenta io_uring e cai para epoll de
forma automática e não-fatal quando a chamada retorna `EPERM`/`ENOSYS` — e bloquear é bom por si
só, já que io_uring é um vetor conhecido de bypass de seccomp em kernels mais antigos.

**Verificado neste host antes de desenhar a política** (não apenas lido na documentação):
`pyseccomp` instala e aplica um filtro de verdade (testado: syscall negada devolve `EPERM`,
demais seguem permitidas); as 3 syscalls do Landlock (`landlock_create_ruleset`,
`landlock_add_rule`, `landlock_restrict_self`) também — um processo de teste confinado a um
diretório permitido lê/escreve nele e tem leitura **negada** (`PermissionError`) num diretório
irmão não declarado.

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

**Status: ✅ concluída** (change `agent-sandbox-seccomp-landlock`, capability `agent-sandbox`).

**Entregue**: `base-image/afsupervisor/sandbox.py` (seccomp via `pyseccomp` + Landlock via `ctypes`
direto); `ExecutionMode.sandboxed` (terceiro valor, ao lado de `legacy`/`reduced`), decidido na
criação do sistema por `provisioning.decide_execution_mode()` (sonda `landlock_abi()` do próprio
processo do portal — não do container de sistema); `require_sandbox` (fail-closed em produção,
`APPAIFORGE_REQUIRE_SANDBOX=false` degrada para `reduced` com aviso em dev/CI sem Landlock, mesmo
precedente do `storage_opt`); confinamento instalado via `preexec_fn` do `subprocess.Popen` que
sobe o harness — no processo **filho**, nunca no supervisor (PID 1), que precisa continuar livre
para gerenciar a app depois.

**Correção de design durante a implementação**: o esboço original cogitava o supervisor se
auto-restringir antes do `exec`. Isso prenderia o supervisor pelo resto da vida do container à
política pensada só para o agente — qualquer caminho que ele precisasse tocar depois (gerenciar a
app, servir o placeholder) e que não estivesse no perfil quebraria o supervisor inteiro.
`preexec_fn` resolve isso: roda no filho, entre o `fork()` e o `exec()`, sem afetar o pai.

**Verificação real (task 7, 2026-11-05, OpenRouter/deepseek, sistema `sandboxed` numa stack e2e
isolada)** — achou e corrigiu 4 lacunas que nenhuma leitura de documentação teria previsto:
1. **`/proc` ausente de `readable_paths`**: o runtime Bun do opencode abortava (`SIGABRT`) ~12s
   depois de subir, sob Landlock — provável leitura de `/proc/self/maps` pelo JIT do JSC para
   gerenciar memória W^X. Não amplia o que o agente já enxerga (supervisor e agente são o mesmo
   uid no mesmo container).
2. **`writable_paths` que ainda não existem no primeiro boot**: Landlock só autoriza um caminho
   que já tem um inode pra abrir; `_add_path_rule` pulava em silêncio qualquer caminho ausente, e
   nenhum dos caminhos de cache do perfil existe antes da primeira escrita real do agente —
   `mkdir('/home/agent/.local')` falhava com `EACCES`. Corrigido: `apply_landlock` cria
   (`os.makedirs`) cada `writable_path` ausente antes de declarar sua regra.
3. **`/etc` ausente**: toda chamada de rede do opencode falhava com `getaddrinfo EAI_AGAIN`,
   mesmo com o DNS do container funcionando normalmente pra qualquer outro processo — o
   resolvedor de rede do Bun lê algo sob `/etc` direto (provável `/etc/resolv.conf`), fora da NSS
   da glibc. Não amplia o que já era acessível (`/etc/shadow`/`/etc/gshadow` são `0640
   root:shadow`, fora do alcance do usuário `agent` de qualquer forma).
4. **`/dev` ausente**: com os 3 achados acima corrigidos, o harness subia e gerava a app, mas `uv
   sync` falhava com "Could not detect either glibc version nor musl libc version" e nenhuma
   dependência era instalada — provável abertura de `/dev/null` por um subprocesso de sondagem do
   `uv`. Perfil final: `readable_paths = [/opencode-config, /usr, /lib, /opt, /proc, /etc, /dev]`.

Com os 4 corrigidos: o agente escreveu `/workspace/app/main.py`, criou `pyproject.toml`, rodou
`uv sync` com sucesso (venv real, `nicegui` instalado), o supervisor trocou o placeholder pela app
automaticamente, a app respondeu `200` tanto direto (porta 8080) quanto via Traefik
(`/apps/etapa2-verify`), e os checkpoints git foram criados — nada precisou de root em nenhum
momento. Cada aprovação de `external_directory` pedida pelo próprio opencode (não-Landlock — gate
de permissão da ferramenta, já corrigido na etapa 1) funcionou normalmente.

**Observação não resolvida, sem evidência de ser causada pelo confinamento**: numa chamada de
continuação do chat pedindo para configurar `uv sync` explicitamente, uma tool call `read` do
opencode (lendo um arquivo de 55 bytes já lido antes com sucesso na mesma sessão) travou por mais
de 3 minutos sem erro nem timeout — interrompida manualmente pelo chat sem efeito colateral
(harness e app seguiram saudáveis). Inspecionado via `/proc/<pid>/task/*/status`+`wchan`: nenhuma
thread do processo estava bloqueada numa syscall (todas em `futex_do_wait`/`ep_poll`, estado
ocioso normal de thread-pool), o que não aponta para Landlock/seccomp como causa — parece uma
falha de aplicação do próprio opencode/Bun (promise perdida, thread-pool starvation). Registrado
aqui para o caso de reaparecer; não bloqueou nenhum critério de aceite desta etapa.

---

## Etapa 3 — Broker de inferência (nenhuma credencial de LLM no container)

**Status: ✅ concluída** (change `inference-broker`, capability `inference-broker`, [ADR 0020](adr/0020-broker-de-inferencia-com-litellm.md)). Verificação real (2026-11-07, OpenRouter/deepseek, stack isolada 8081): execução real completa via opencode → broker → LiteLLM → OpenRouter com `docker exec env` mostrando só o token opaco; revogação por sistema (token antigo 401, container recriado com o token da nova versão) e por sessão (403 com a run ativa); interrupção propagada ao broker; reprovision reentregando o token idêntico; uso/custo registrado fim a fim via callback (idempotente). Achados da verificação (banco próprio do LiteLLM + `STORE_MODEL_IN_DB`, segredo HMAC compartilhado com o broker, reescrita do model pelo broker, callback customizado no lugar do logger Enterprise, tokens de serviço em `deploy/.env`) registrados no design da change.

**Entregue**: token opaco HMAC versionado por sistema (`inference_token.py`, revogação por incremento de versão + ação administrativa); broker compartilhado (`broker_app.py`/`broker.py`) com validação de token, resolução de run/sessão no portal, injeção de credencial no caminho de saída, allowlist de destino, streaming sem buffer e cancelamento via `/internal/cancel`; revogação seletiva de sessão (`chat_sessions.inference_revoked`, ação na UI do chat); uso/custo via callback do LiteLLM com idempotência (`token_usage.cost`, `external_id`); LiteLLM e broker nos dois compose, com o portal sincronizando as chaves do catálogo para a API administrativa do LiteLLM (fonte única, ADR 0007); rollout por `APPAIFORGE_INFERENCE_BROKER_ENABLED`. Spikes S4/S6/S7 fechados empiricamente (incluindo o achado de que o opencode usa `/v1/responses`).

**Objetivo**: nem a chave real do provedor nem a virtual key do LiteLLM entram no container. O
container carrega apenas um **token opaco emitido pelo portal**, que um broker troca pela
credencial no caminho de saída.

**Por que híbrido, e não a virtual key no env** (decidido em 2026-11-04): a credencial é injetada
como env var do container, montada em `_provider_env` dentro do dict que vai para o
`containers.run` ([`provisioning.py:196`](../portal/appaiforge/provisioning.py)). Env var de
container é fixada na criação, e o opencode lê o `opencode.json` do cwd só no boot. Então
**virtual key por sessão de chat é impossível via env**: trocar a key exigiria recriar o
container, disparando o aviso *"Contexto do agente reiniciado"* a cada troca de sessão. Ou se
aceita granularidade por sistema, ou se põe uma camada de troca. Escolhemos a camada.

**Escopo**
- **LiteLLM** permanece como backend de credencial e tradução de dialeto — o "buy" da etapa.
- **Broker** novo: serviço **compartilhado** (não um sidecar por container) que valida o token do
  container, resolve o run e a sessão ativos, escolhe a virtual key correspondente, injeta no
  header e encaminha ao LiteLLM.
- O container recebe `baseURL` → broker e, na env de credencial (cujo **nome** vem do perfil da
  etapa 1, via `from_provider`), um **token opaco do portal** em vez de chave. Isso satisfaz o
  client do opencode, que exige credencial configurada, e o token é **validado** pelo broker, não
  ignorado.

**A atribuição de sessão sai de graça**: o spec `agent-harness` garante *"Fila de um agente por
sistema"* — no máximo um run ativo por sistema por vez. O broker não precisa de header nenhum do
opencode (que não manda `session_id` na chamada ao LLM): ele pergunta ao portal qual run e sessão
estão ativos naquele sistema. A serialização que já existe por razão de produto dá a atribuição.

**Por que o broker pode ser compartilhado**: porque a identidade viaja no token, ele **não depende
da forma do perímetro** (sidecar em netns no Docker vs `iptables` em k8s). Foi isso que permitiu
trazer a camada de troca para esta etapa em vez de esperar a etapa 5.

**Por que LiteLLM e não escrever**: multi-agente é **multi-dialeto**. opencode fala
OpenAI-compatible; Claude Code fala Anthropic Messages. O LiteLLM expõe os dois — inclusive
`/v1/messages` e `/v1/messages/count_tokens`, repassando `anthropic-beta`/`anthropic-version` —
e traduz entre eles. Com um agente dava para improvisar; com três, não. O broker fica **agnóstico
de dialeto**: valida, injeta header e repassa.

**Ganho colateral**: o `_token_count()` com gambiarra por provedor
([`opencode.py:119`](../portal/appaiforge/harness/opencode.py)) morre. Tokens e custo passam a
vir do LiteLLM, normalizados, reforçando o requirement *Visibilidade de uso de tokens*. E o broker
já conhece o `run_id`, o que dá correlação real (não por atributo) ao span de LLM na etapa 6.

**Riscos próprios desta etapa** — são o custo do híbrido, e precisam de teste como o `gate.py`:
- **SSE e cancelamento**: o broker tem que repassar streaming sem buffering, com backpressure e
  timeout, e o `/session/{id}/abort` precisa cancelar a requisição ao provedor. Proxy de streaming
  é onde moram os bugs sutis, e um proxy que bufferiza quebra o requirement *"Streaming do
  trabalho em tempo real"*.
- **Open relay interno**: o broker precisa de allowlist de destino e recusar requisição sem token
  válido; sem isso ele vira saída livre para quem estiver na rede interna.
- **Header do agente não sobrescreve a injeção**: o broker descarta credencial vinda do cliente.
- **Superfície de revogação única**: com o container sem key, revogar a virtual key no LiteLLM não
  derruba nada — o broker pediria outra. O broker **tem que ser a autoridade** de revogação
  (token do container e mapeamento de sessão), para não haver duas superfícies que precisam
  concordar.

**Entrega verificável**: `docker exec <sys> env` não mostra nenhuma credencial utilizável, só o
token opaco; revogar o token do container ou o mapeamento de sessão no broker derruba o acesso
daquele sistema ou sessão sem afetar os outros.

**Não resolve ainda**: nada impede o agente de chamar `api.z.ai` direto se descobrir o endereço.
O broker está **configurado**, não **imposto** — etapa 5.

**Specs/ADR**: `llm-provider-keys`. ADR 0020, registrando o híbrido como decisão e a virtual key
no env como alternativa descartada, com o motivo (granularidade por sessão inviável por env).

---

## Etapa 4 — Proxy de banco e o gate no data plane

**Status: ✅ concluída** (change `db-proxy-gate-data-plane`, [ADR 0021](adr/0021-gate-de-sql-no-data-plane-via-sidecar-proxy.md)).
Sidecar real por sistema (`network_mode: container:<id>`) com proxy de wire protocol Postgres e
MySQL em Python asyncio, validado contra bancos reais (spikes S8 e MySQL) e com testes de
integração/E2E ponta a ponta contra Docker real: statement confirmável em modo `enforce` segura a
conexão e só executa após aprovação pelo card novo do chat (distinto do card antigo); modo `shadow`
(default) executa tudo e só audita; origem `agente`/`app` atribuída por listener separado;
container do sistema sem credencial usável no env/cmdline, só o sidecar guarda a credencial real.
Ferramenta de comparação sombra-vs-globs (`gate_comparison.py`, CLI `compare-gate-decisions`)
construída e testada, mas **ainda não rodou contra uso real** — por isso o default continua
`shadow` e os globs de `permission.bash` continuam como cinto-e-suspensório: trocar o default para
`enforce` (e aí sim apagar os globs de SQL) depende de medir falso-positivo em produção, não de
mais código. Correção de rota em relação ao parágrafo original abaixo: o `reply_gate`
([`base.py:50`](../portal/appaiforge/harness/base.py)) **não saiu** do `HarnessPort` — é o
mecanismo genérico de resposta a qualquer `permission.asked` do opencode (inclusive não-SQL, ex.:
acesso a diretório fora do workspace), que esta change não tinha motivo para tocar.

**Objetivo**: o gate funciona independente de **como** a SQL foi emitida, e independente de qual
agente está rodando. É a etapa que destrava o multi-agente.

**Escopo**: proxy de wire protocol Postgres/MySQL num **sidecar próprio por sistema**,
compartilhando o network namespace do container do agente (ao contrário do broker de inferência
da etapa 3, que é compartilhado) — o DSN de loopback e o truque de porta da etapa 5 exigem o
gate dentro do netns. O sidecar guarda as
credenciais reais e as injeta. O agente recebe DSN de loopback sem senha. O `sqlgate`, o
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

**Status: ✅ concluída** (change `agent-network-perimeter`, [ADR 0022](adr/0022-confinamento-de-rede-por-porta-tcp-via-landlock.md)) —
**com um corte de escopo decidido em operação**: só a restrição de porta TCP (fecha o bypass dos
proxies de banco/broker). A segunda metade do texto original abaixo (negar 443, proxy HTTP(S) para
pip/npm/LLM direto) **não foi implementada nesta change** — decisão de escopo, registrada no
proposal.md: exige construir uma peça de infraestrutura nova (proxy com CONNECT tunneling) e
decidir o que fazer com a chamada direta ao provedor de LLM quando o broker está desligado (hoje o
padrão); fica para uma change futura separada, sem bloquear o objetivo principal, que não depende
disso. O texto original do roadmap (abaixo) é mantido como registro da intenção completa.

**Objetivo**: fechar o bypass das etapas 3 e 4, **em Docker local, sem privilégio nenhum**,
reusando o Landlock da etapa 2.

**O truque**: o sidecar do gate compartilha o network namespace do container do agente
(`network_mode: container:<id>`), então os dois veem o mesmo loopback. O proxy escuta em portas
próprias (ex.: 15432, 13306, 18080). O Landlock do agente usa `LANDLOCK_ACCESS_NET_CONNECT_TCP`
(ABI 4+; o host está em ABI 8) para permitir **só** essas portas, negando 5432/3306/443 em geral.
`BIND_TCP` liberado só em 8080 (app) e 4096 (harness).

~~`BIND_TCP` liberado só em 8080 (app) e 4096 (harness)~~ — corrigido na implementação: o agente
confinado nunca escuta a porta da app (8080); quem a abre é o processo da app gerada, que roda fora
do `preexec_fn` de confinamento desde a etapa 2 (nunca teve Landlock, nem de filesystem, e isto não
muda aqui). `BIND_TCP` do agente é só a 4096 (harness). E **443 continua aberto** (corte de
escopo acima), não negado como o texto original planejava.

Funciona porque **Landlock é por árvore de processos, não por namespace**: o agente está
confinado; o processo do proxy, no outro container, não.

O **broker de inferência da etapa 3 é compartilhado**, não um sidecar: o agente o alcança por
host:porta na rede interna. Como as regras de rede do Landlock são por **porta** e agnósticas de
endereço, liberar a porta do broker cobre os dois casos sem mudança. E vale ser explícito: a
**injeção de credencial é da etapa 3**; a etapa 5 só impõe que o caminho seja usado.

HTTP(S) geral (`pip`, `npm`, `uv`): forçar `HTTP_PROXY`/`HTTPS_PROXY` e negar a 443. Ferramenta
que ignora proxy env simplesmente falha — fail-closed, aceitável. **Fora de escopo nesta change**
(ver corte de escopo acima) — fica para uma change futura.

**Spike obrigatório antes de comprometer**: confirmar que as regras de rede do Landlock se
aplicam a conexões de **loopback** (são só por porta, agnósticas de endereço — mas isso é
load-bearing aqui). ✅ Confirmado por spike real, virado teste (`test_apply_landlock_net_real_restringe_porta_tcp_sem_enfraquecer_fs`):
porta liberada conecta, porta não liberada nega com `PermissionError` (não `ConnectionRefusedError`),
e a camada de filesystem da etapa 2 continua valendo depois do segundo `landlock_restrict_self`.

**Entrega verificável**: o agente não alcança nada além das portas do gate (ressalvada a 443/80/53,
ver corte de escopo). Sem eBPF, sem iptables, sem daemon privilegiado, sem reboot. Provado em
integração real (`test_network_perimeter.py`): de dentro de um sistema `sandboxed` com conexão
Postgres real, conectar no `agent_port` do proxy funciona; conectar direto na porta real do
Postgres — alcançável na rede, só negada pelo Landlock — falha.

**Não resolve ainda**: exfiltração **pelo prompt** — o endpoint do LLM é legítimo e o agente pode
mandar conteúdo do workspace por ele. Irredutível; o próprio OpenShell admite o mesmo limite.
Também não resolve (corte de escopo desta change, não lacuna esquecida): acesso direto a provedor
de LLM e a registros de pacote continuam por 443, sem proxy HTTP(S) forçado.

**Specs/ADR**: extensão de `agent-sandbox`. ADR 0022.

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
partir da identidade da conexão. Exceção: o **span `llm.request` vem do broker da etapa 3**, que
já resolve run e sessão pelo token — ali a correlação é direta, não inferida.

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
- **Paralelizável**: 3 e 4 foram planejadas compartilhando um sidecar, mas a 3 terminou
  compartilhada (sem sidecar) e a 4 ganha sidecar próprio — independentes entre si; a 4 fica em
  sombra primeiro. A 6 pode começar junto da 3 (o LiteLLM já emite spans de graça).
- **Primeiro marco demonstrável**: fim da etapa 3 — container sem root, confinado, e sem chave de
  LLM dentro. Três coisas que hoje são o contrário, sem ter mexido no gate.
- **Mapa OpenSpec**: cinco changes (1, 2, 3, 4, 5+6), quatro ADRs novos a partir do 0018, duas
  specs novas (`agent-sandbox`, `agent-policy`), reescrita de `destructive-gate`, ajustes em
  `container-lifecycle` e `llm-provider-keys`.

## Spikes abertos

| # | Pergunta | Bloqueia |
|---|---|---|
| S1 | Regras de rede do Landlock se aplicam a loopback? | Etapa 5 |
| ~~S2~~ | ✅ `pyseccomp` dá conta sozinho — verificado neste host (filtro real, nega syscall com EPERM, resto passa) | Etapa 2 |
| ~~S3~~ | ✅ `memfd_create` quebraria o JIT de Bun (sem MPK neste host) — tirado do denylist; `io_uring_setup` confirmado seguro (fallback automático do Bun) | Etapa 2 |
| S4 | LiteLLM cobre todos os provedores do catálogo (GLM, OpenRouter, openai-compatible)? | Etapa 3 |
| S5 | Quanto falso-positivo o modo sombra do gate revela? | Etapa 4 |
| S6 | SSE e cancelamento atravessam o broker sem buffering? | Etapa 3 |
| S7 | O opencode aceita token opaco como credencial, sem validar formato? | Etapa 3 |

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
é referência pronta. O híbrido escolhido na etapa 3 **é** o modelo *endpoint-bound por
placeholder* deles — o agente nunca vê credencial, e ela é adicionada só em requisições destinadas
a endpoint aprovado — com o LiteLLM no papel de credential store, em vez de reescrevermos
passthrough de `/v1/messages`, SSE e `count_tokens`. Que uma implementação independente tenha
convergido no mesmo desenho é o melhor sinal que temos de que ele está certo.

## Referências

- [Landlock — kernel.org](https://docs.kernel.org/userspace-api/landlock.html) · [landlock(7)](https://man.archlinux.org/man/landlock.7.en)
- [OpenShell: arquitetura](https://docs.nvidia.com/openshell/about/architecture) · [segurança](https://docs.nvidia.com/openshell/latest/security)
- [Anthropic sandbox-runtime](https://github.com/anthropics/sandbox-runtime) (bubblewrap + proxy com allowlist por SNI)
- [LiteLLM `/v1/messages`](https://docs.litellm.ai/docs/anthropic_unified/) · [virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [KubeArmor: spec de política](https://docs.kubearmor.io/kubearmor/documentation/security_policy_specification) · [matriz de suporte](https://github.com/kubearmor/KubeArmor/blob/main/getting-started/support_matrix.md)
- [Istio Proxy Redirection](https://github.com/istio/istio/wiki/Proxy-Redirection) (padrão do initContainer iptables)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks) · [modo headless](https://docs.claude.com/pt/docs/claude-code/sdk/sdk-headless)
- [pg-proto](https://docs.rs/pg-proto/latest/pg_proto/) (wire protocol Postgres para proxies)
