# AIDB

Portal que cria **sistemas de gestão com IA sobre seus bancos de dados**: você cadastra um sistema, conecta um banco (PostgreSQL, MySQL ou BigQuery), conversa com o agente pelo chat do portal e ele gera uma app administrativa (NiceGUI, 100% Python) que sobe automaticamente e fica acessível em `/apps/<slug>`.

- Decisões de arquitetura: [`docs/adr/`](docs/adr/README.md) (21 ADRs, formato MADR)
- Especificações: `openspec/specs/` (13 capacidades); o histórico de mudanças fica em `openspec/changes/archive/` (change fundadora: `2026-11-02-appai-forge-mvp`)

## Arquitetura em uma linha

Traefik (edge) → portal FastAPI+NiceGUI (auth/RBAC/chat/proxy) → um container por sistema (supervisor + `opencode serve` + app gerada) → banco de produção (PostgreSQL, MySQL ou BigQuery) via MCP somente leitura (agente) e driver direto (app).

## Requisitos

- Docker 24+ com Compose v2
- Porta 80 livre
- ~2 GB RAM por sistema ativo (padrão; ver limites abaixo)

## Subir o stack do zero

```bash
cd deploy
docker compose up -d --build          # postgres + mysql + traefik + portal
docker compose exec portal alembic upgrade head   # migrações (opcional: o portal cria o schema no boot)
```

- O serviço `mysql` do compose existe só como banco de teste para cadastrar conexões MySQL (host `mysql`, porta 3306, banco/usuário/senha `appaiforge`); as portas dos bancos não são publicadas no host.
- Portal: http://localhost (admin semeado em dev: `admin@appaiforge.local` / `admin123` — `APPAIFORGE_SEED_DEMO_ADMIN=1` no compose)
- Health: http://localhost/api/health

### Bootstrap do admin (produção)

Em vez do admin semeado, crie o primeiro admin por CLI:

```bash
docker compose -f deploy/docker-compose.yml exec portal appaiforge create-admin --email voce@empresa.com --password 'uma-senha-forte'
# e remova a variável APPAIFORGE_SEED_DEMO_ADMIN do compose
```

## Chave de LLM (para geração real)

O padrão do produto é GLM/Z.ai (ADR 0012). Obtenha uma chave e cadastre-a cifrada:

```bash
docker compose -f deploy/docker-compose.yml exec portal appaiforge set-provider-key --provider glm --key 'SUA_CHAVE_ZHIPUAI'
```

> Os comandos `docker compose -f deploy/...` funcionam de qualquer diretório; se preferir, `cd deploy` antes e use `docker compose exec portal ...` sem o `-f`.

Além do GLM, o admin pode cadastrar na UI provedores que falam o padrão OpenAI (o OpenRouter é um preset); os modelos são descobertos na própria rota do provedor, e cada sistema escolhe provedor e modelo. Chaves são globais por provedor, cifradas, e podem ser cadastradas, testadas e removidas pela UI de admin.

Sem chave, o portal opera em **modo fake** (ver abaixo) — todo o resto funciona. O compose sobe em `fake` por padrão; para usar o agente real defina `APPAIFORGE_HARNESS_MODE=opencode` (por exemplo em `deploy/.env`, que não vai para o git).

**Troubleshooting de provedor**: se uma execução falha com *"o provedor de LLM não retornou resposta (verifique chave, saldo e modelo configurados)"*, valide a chave diretamente — exemplo do erro `1113` (saldo insuficiente na Z.ai):

```bash
curl -s https://api.z.ai/api/coding/paas/v4/chat/completions \
  -H "Authorization: Bearer SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"model":"glm-4.6","messages":[{"role":"user","content":"ok"}]}'
```

## Broker de inferência (opcional — etapa 3 do confinamento)

Por padrão, a chave do provedor entra no container do sistema via env var. Com o **broker de inferência** ligado ([ADR 0020](docs/adr/0020-broker-de-inferencia-com-litellm.md)), o container passa a carregar apenas um **token opaco** — o broker valida o token, resolve a execução ativa e injeta a credencial só no caminho de saída, com o [LiteLLM](https://docs.litellm.ai/) como backend de credencial e tradução de dialeto.

Para ligar, defina em `deploy/.env`:

```bash
APPAIFORGE_INFERENCE_BROKER_ENABLED=true
APPAIFORGE_LITELLM_API_KEY=sk-uma-chave-master-do-litellm
APPAIFORGE_INFERENCE_BROKER_SERVICE_TOKEN=um-token-entre-portal-e-broker
```

e suba o stack (`docker compose -f deploy/docker-compose.yml up -d --build`). Os serviços `litellm` e `broker` sobem na rede interna, sem porta publicada.

> **Banco do LiteLLM**: o serviço exige um database próprio (`litellm`) no Postgres — a migração Prisma cria as tabelas, mas não o database. O compose E2E cria no init do volume; no stack principal, crie uma vez (stack novo ou volume já existente):
>
> ```bash
> docker compose -f deploy/docker-compose.yml exec postgres \
>   psql -U appaiforge -c "CREATE DATABASE litellm;"
> ```
>
> Sem isso o `litellm` fica reiniciando até o banco existir; depois de criado, se recupera sozinho.

Como funciona:

- **Chaves**: o portal continua sendo a fonte única (cifradas no Postgres, ADR 0007). Ao cadastrar/remover uma chave na UI — e no boot do portal — os deployments são empurrados para a API administrativa do LiteLLM. Nada de chave de provedor em arquivo ou env do compose.
- **Containers**: com a flag ligada, sistemas novos (e existentes, recriados pela reconciliação) recebem o token opaco na env de credencial e o `opencode.json` aponta o provedor para o broker. `docker exec <sys> env` mostra só o token.
- **Revogação**: dono/admin pode revogar o acesso de um sistema (aba Configurações → "Revogar acesso de inferência": a versão do token sobe e o container é recriado) ou de uma sessão (botão na lista de sessões do chat — só aquela sessão é bloqueada).
- **Uso/custo**: o LiteLLM envia tokens e custo por execução para o portal (callback idempotente); a contagem caseira por provedor fica desligada.
- **Rollback**: desligar a flag e recriar os sistemas volta a injetar a chave do catálogo.

> A revogação por sistema e a rota do broker são **configuradas, não impostas** — fechar o perímetro de rede é a etapa 5 do [roadmap](docs/roadmap-confinamento-do-agente.md).

## Criar um sistema (fluxo do usuário)

1. Login como **editor** → "Novo sistema" → nome + slug.
2. Aguarde o badge **ativo** (container provisionado, app em `/apps/<slug>` mostrando "ainda não gerada").
3. Na página do sistema: **Conexões** → escolha o tipo e cadastre o banco, testado antes de salvar (vira MCP somente leitura do agente + `DATABASE_URL_<NOME>` da app):
   - **PostgreSQL / MySQL**: host, porta, banco, usuário e senha.
   - **BigQuery**: projeto, dataset e JSON de Service Account (guardado cifrado).
   - Cada conexão tem um estado de saúde monitorado (ver Operação).
4. **Chat de geração**: peça em PT-BR ("crie um CRUD da tabela clientes com busca e formulário"). Acompanhe o streaming, interrompa se preciso (detalhes em *Chat* abaixo).
5. Ao concluir: checkpoint criado, app reiniciada e servida em `/apps/<slug>`; "Abrir app" entra com sua identidade (SSO por token HMAC).
6. **Checkpoints** → "Restaurar" para voltar o código a qualquer ponto (a app reinicia no estado restaurado).

## Chat

- **Sessões**: cada editor mantém várias sessões nomeadas por sistema (criadas na primeira mensagem, renomeáveis, com troca na lista). O agente mantém o contexto dentro da sessão; se o contexto for reiniciado (container recriado, sessão inválida) o chat avisa.
- **Mensagens**: data e hora ao lado do nome de quem enviou, no fuso `APPAIFORGE_DISPLAY_TIMEZONE`. Os marcadores de execução (iniciada, concluída, interrompida, erro) aparecem em português.
- **Disponibilidade**: abaixo do chat, uma bolinha verde indica agente livre e uma amarela pulsando indica trabalho em curso (sem animação se o sistema operacional pede movimento reduzido).
- **Debug**: comandos executados e arquivos alterados só aparecem com a chave **Debug** ligada; ligar e desligar não perde histórico.
- **Artifacts**: o agente pode responder com blocos ` ```echart `, ` ```table ` e ` ```html `, que o chat renderiza como gráfico, tabela interativa e HTML em sandbox.
- **Checkpoint manual**: o botão informa se criou um checkpoint ou se não havia alteração a salvar.

## Editor

Aba ao lado do Chat, visível para quem gerencia o sistema (mesmo acesso das demais abas). Mostra, à esquerda, a árvore de arquivos da pasta onde o agente gera o projeto (`<workspace>/app`, sem `.venv`/`__pycache__`/`.git`/caches do NiceGUI) e, à direita, o conteúdo do arquivo selecionado com destaque de sintaxe pela extensão. **Somente leitura**: o painel nunca aceita edição, e nada feito nessa aba grava no workspace. A árvore reflete o estado atual do workspace (não um checkpoint específico) e se atualiza sozinha a cada 2s, então o editor vê o resultado de uma geração sem precisar trocar de aba e voltar. Um arquivo binário ou ilegível como texto mostra um aviso no lugar do conteúdo, em vez de falhar.

## Aparência

Na topbar o usuário escolhe o modo (Light, Dark ou Pastel) e a cor de destaque (Índigo, Teal, Âmbar ou Violeta). A preferência fica salva por usuário e é aplicada ao portal inteiro sem flash. Todas as 12 combinações respeitam contraste WCAG AA; ao criar componentes novos, use os tokens de `portal/appaiforge/ui/theme.py` em vez de cores fixas.

## Gate de operações destrutivas

Toda SQL que toca os bancos das conexões passa pelo **gate** (classificador canônico com sqlglot — [ADR 0017](docs/adr/0017-gate-de-operacoes-destrutivas-com-classificador-sql.md), spec `destructive-gate`):

| Classe | Exemplo | Comportamento |
|---|---|---|
| **normal** | `DELETE FROM clientes WHERE id = $1` (escopo por chave) | executa sem atrito |
| **confirmável** | `DELETE FROM clientes` ou `WHERE cidade = 'X'` | **sempre recusada** em `enforce` ([ADR 0023](docs/adr/0023-confirmavel-recusado-direto-sem-pedir-aprovacao.md)) |
| **bloqueada** | DDL (`DROP`/`TRUNCATE`/`ALTER`/...) | **sempre recusada** |

Desde a etapa 4 do confinamento ([ADR 0021](docs/adr/0021-gate-de-sql-no-data-plane-via-sidecar-proxy.md)), o gate roda no **data plane**: cada sistema com conexão Postgres/MySQL ganha um **sidecar** (`<slug>-dbgate`, mesmo network namespace do container do sistema) que fala o protocolo de fio do banco e classifica cada statement antes de repassá-la — não depende de reconhecer SQL dentro de texto de bash, e cobre tanto o agente quanto a app gerada. O container do sistema nunca vê a credencial real: `DATABASE_URL_<NOME>` e o comando do MCP recebem um DSN de loopback sem usuário/senha; só o sidecar guarda o segredo e abre a conexão de verdade.

- **Pelo agente/app**: dois listeners por conexão (um para o agente/MCP, outro para a app gerada via `DATABASE_URL_<NOME>`) atribuem a origem sem ambiguidade. Em `enforce`, `bloqueada` e `confirmável` têm o **mesmo tratamento**: nenhuma das duas chega ao banco, nenhuma pede decisão de ninguém — o proxy recusa na hora (erro de protocolo ao cliente). Achado ao vivo que motivou isso ([ADR 0023](docs/adr/0023-confirmavel-recusado-direto-sem-pedir-aprovacao.md)): segurar `confirmável` e pedir aprovação por um card genérico deixava passar um `DELETE` sem `WHERE` disfarçado, se alguém aprovasse por hábito. Quando há uma run ativa do agente, a recusa aparece no chat com a statement e o motivo.
- **Dois modos, por flag** (`DB_GATE_MODE`): `enforce` (default) torna o proxy o gate de verdade — `bloqueada`/`confirmável` são recusadas na hora e os globs de SQL somem do `permission.bash` do agente (ficam só os não-SQL); `shadow` classifica e **audita sem bloquear nada**, útil pra observar um sistema específico antes de confiar nele (`appaiforge compare-gate-decisions`, ver [roadmap](docs/roadmap-confinamento-do-agente.md)). Trocar entre os dois é mudança de configuração, não de código.
- **Na app gerada**: a camada `dbgate.py` (obrigatória nas guidelines) dispara um diálogo com a contagem estimada de linhas antes de executar operações confirmáveis; DDL é recusada — cinto-e-suspensório com o proxy, que já classifica a mesma statement antes dela chegar ao banco. Essa confirmação é da interface da app pros usuários dela, sem relação com o chat agente↔editor acima.
- **Auditoria**: toda decisão (aprovada/recusada/bloqueada/sombra) fica na seção "Gate de destrutivas" da página do sistema, com autor, SQL, origem e data.
- Apps geradas **antes** desta mudança migram para a camada na próxima edição pelo agente.

## Segurança: confinamento do agente

Cada sistema roda num container próprio sob um de três **modos de execução**, fixado na criação
e nunca trocado automaticamente ([ADR 0018](docs/adr/0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md),
[ADR 0019](docs/adr/0019-sandbox-seccomp-landlock-no-supervisor.md), roadmap
[`docs/roadmap-confinamento-do-agente.md`](docs/roadmap-confinamento-do-agente.md)):

| Modo | Usuário | Capabilities | Landlock + seccomp |
|---|---|---|---|
| `legacy` | root | todas | não |
| `reduced` | `agent` (uid 1000) | nenhuma (`cap_drop: ALL`) | não |
| `sandboxed` | `agent` (uid 1000) | nenhuma | **sim** |

Sistema novo recebe `sandboxed` automaticamente se o host suporta Landlock; sem suporte, cai para
`reduced` com aviso (ou recusa a criação com `APPAIFORGE_REQUIRE_SANDBOX=true`, modo fail-closed
de produção). Sistemas criados antes do ADR 0018 ficam em `legacy` — ver "Migrar um sistema para
`sandboxed`" abaixo.

**Como o confinamento funciona** (modo `sandboxed`): o supervisor (`afsupervisor`, PID 1 do
container) aplica dois mecanismos auto-impostos e não-privilegiados no processo **filho** que vai
virar o agente (`opencode serve`), nunca em si mesmo — ambos são herdados por todo processo que o
agente gerar (bash, python, o script que ele escrever) e **irrevogáveis** depois de aplicados:

- **seccomp** nega um denylist de syscalls perigosas (`ptrace`, `bpf`, `mount`, `setns`,
  `perf_event_open`, `process_vm_readv`/`writev`, `pivot_root`, `io_uring_setup`, `unshare` com
  `CLONE_NEWUSER`) — tudo o mais é permitido.
- **Landlock de filesystem** nega acesso fora do declarado no perfil do agente
  (`appaiforge/agent_profiles.py`): leitura+execução só em `/workspace`, `/opencode-config`,
  `/usr`, `/lib`, `/opt`, `/proc`, `/dev` e um conjunto explícito de arquivos sob `/etc`
  (resolução de nome, fuso horário, cache do linker, cadeia de certificados — **não** o diretório
  inteiro); escrita só em `/workspace`, `/tmp` e os caches do `$HOME` do agente. Qualquer coisa
  fora dessas listas — `/etc/passwd`, `/etc/shadow`, `/root`, os workspaces de outros sistemas —
  fica negada pelo kernel, não por um pedido de permissão que o agente poderia simplesmente
  receber "sim" de um editor apressado.
- **Landlock de rede** ([ADR 0022](docs/adr/0022-confinamento-de-rede-por-porta-tcp-via-landlock.md)),
  empilhado por cima do de filesystem: conexão TCP de saída só nas portas calculadas para o
  sistema — o `agent_port` de cada conexão cadastrada (proxy de gate de banco, etapa 4), a porta do
  broker de inferência quando habilitado, a porta do proxy HTTP(S) de saída (abaixo), e sempre 53
  (DNS por TCP). Fecha o bypass que as etapas 3/4 deixavam aberto: antes, um agente confinado por
  filesystem ainda alcançava o Postgres/MySQL real direto, por fora do proxy, bastando descobrir o
  endereço — a regra de porta do Landlock é agnóstica de endereço, então nega isso mesmo que o
  agente ache o host real.

**O que isso substitui**: a permissão `external_directory` do próprio opencode (pedia confirmação
no chat toda vez que o agente tocava um caminho fora do workspace, inclusive **falsos-positivos**
de caminho absoluto já dentro dele) hoje é liberada sem perguntar
(`permission.external_directory: "allow"`) — a barreira real passou a ser o Landlock, que o
sistema operacional aplica de verdade e não depende de ninguém clicar em "Aprovar".

**Proxy HTTP(S) de saída** ([ADR 0024](docs/adr/0024-proxy-http-s-de-saida-obrigatorio-por-sistema.md)):
443 e 80 saíram da lista fixa do Landlock — a única saída HTTP(S) do agente passa por um sidecar
(`<slug>-httpsproxy`, mesmo network namespace do sistema), que só libera `CONNECT`/requisição HTTP
para um destino (`host:porta`) numa **allow-list calculada por sistema**: o host do provedor de LLM
configurado (quando o broker está desligado) ou o host:porta do broker (quando está ligado — nunca
os dois), mais os registros de pacote (`pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`).
`HTTP_PROXY`/`HTTPS_PROXY` são injetadas automaticamente no ambiente do container; o proxy nunca
decripta TLS, só faz o túnel.

- **Acesso à internet** (toggle na aba Configurações, por sistema): desligado, o proxy não libera
  nenhum destino externo — o broker de inferência (quando habilitado) não é afetado, porque nunca
  passou por este proxy.
- **Modo restrito** (toggle + aba Domínios, por sistema): ligado, a allow-list acima é **substituída
  por completo** pela lista de domínios cadastrada ali — nasce pré-populada com os registros de
  pacote, editável pelo editor do sistema (mesmo acesso da aba Conexões).

**Limites aceitos por ora**: exfiltração via LLM pelo próprio prompt é um limite irredutível (o
endpoint é legítimo, o agente pode mandar conteúdo do workspace por ele). Nenhuma das camadas de
Landlock cobre a app gerada, que roda sem confinamento desde sempre. Sistemas em `legacy`/`reduced`
não têm nenhuma (ou só a de filesystem) dessas garantias.

### Migrar um sistema de `legacy` para `sandboxed`

Não existe CLI/UI para isso (modo é "fixado na criação e imutável" por desenho) — foi feito uma
vez, manualmente, para os sistemas que existiam antes do ADR 0018. Se precisar de novo: sistemas
`legacy` rodam como root, então o workspace inteiro é **dono de root** — trocar só o modo sem
corrigir isso prende o agente (agora uid 1000) fora dos próprios arquivos. A ordem importa:

```bash
# 1. dono do workspace para o uid do agente (ANTES de trocar o modo — enquanto
#    o container antigo ainda roda como root, o bind do host já está acessível
#    de fora dele via outro container efêmero com a mesma imagem)
docker run --rm --user root -v /opt/appaiforge/workspaces/<slug>:/workspace \
  appaiforge/base:0.1.0 chown -R 1000:1000 /workspace

# 2. troca o modo no banco e recria o container (dentro do container do portal)
docker exec appaiforge-portal-1 python -c "
from appaiforge.db import session_scope
from appaiforge.models import System, ExecutionMode
from appaiforge.services.systems import get_system
from appaiforge.provisioning import provision_system

with session_scope() as s:
    row = s.query(System).filter(System.slug == '<slug>').one()
    row.execution_mode = ExecutionMode.sandboxed
    system_id = row.id

provision_system(get_system(system_id))
"
```

Recriar o container invalida qualquer sessão de chat aberta nesse sistema (reabre sozinha na
próxima mensagem). Confirme depois: `docker inspect appaiforge-sys-<slug> --format '{{.Config.User}}'`
deve mostrar `1000:1000`, e `docker exec appaiforge-sys-<slug> id` deve mostrar o usuário `agent`.

## Configuração (env `APPAIFORGE_*`)

| Variável | Padrão | O quê |
|---|---|---|
| `DATABASE_URL` | postgres do compose | metadados do portal |
| `SECRET_KEY` | — | **obrigatória em produção** (deriva a cifra de segredos) |
| `HARNESS_MODE` | `opencode` (no compose: `fake`) | `fake` = agente determinístico sem LLM (dev/E2E) |
| `FAKE_DELAY` | `0.15` | ritmo do harness fake em segundos |
| `BASE_IMAGE` | `appaiforge/base:0.1.0` | imagem dos containers de sistema |
| `CONTAINER_CPUS` / `CONTAINER_MEM_MB` / `CONTAINER_DISK_GB` | 2 / 2048 / 10 | limites por sistema (ADR 0013) |
| `CONTAINER_PIDS_LIMIT` | 512 | teto de processos por container (ADR 0018) |
| `MAX_SYSTEMS` | 10 | teto de sistemas simultâneos |
| `HEALTH_INTERVAL` | 15 | sonda de saúde das apps (segundos) |
| `WORKSPACES_DIR` / `HOST_WORKSPACES_DIR` | /workspaces | raiz dos workspaces (bind compartilhado) |
| `DYNAMIC_CONFIG_DIR` | /dynamic | rotas dinâmicas do Traefik (volume compartilhado) |
| `CONFIGS_DIR` / `HOST_CONFIG_DIR` | /configs | config do agente (MCP, provedor, chaves) **fora do workspace**, montada read-only no container do sistema |
| `DISPLAY_TIMEZONE` | America/Sao_Paulo | fuso das datas exibidas (gravadas em UTC) |
| `INFERENCE_BROKER_ENABLED` | `false` | broker de inferência: token opaco no container + LiteLLM (ADR 0020) |
| `LITELLM_API_KEY` / `INFERENCE_BROKER_SERVICE_TOKEN` | — | master key do LiteLLM e segredo portal↔broker (obrigatórias com o broker ligado) |
| `DB_GATE_MODE` | `enforce` | `enforce` o sidecar recusa bloqueada/confirmável na hora, sem aprovação (ADR 0021/0023); `shadow` audita sem bloquear |
| `DB_GATE_PROXY_SERVICE_TOKEN` | — | segredo compartilhado entre o sidecar e o portal (mesmo padrão do broker) |
| `SEED_DEMO_ADMIN` | — | `1` semeia o admin de dev quando não há usuários (nunca em produção) |

Limites: CPU/memória aplicados via Docker; **quota de disco** requer storage driver com suporte a `storage-opt` (overlay2/ext4 não suporta — o container sobe sem quota e o portal registra a ressalva).

## Testes (três camadas — ADR 0016)

```bash
cd portal
uv sync                                  # deps (Python 3.12)
docker compose -f ../deploy/docker-compose.yml up -d --build   # stack para E2E

uv run pytest tests/unit                 # unitários (rápidos)
uv run pytest tests/bdd                  # BDD: cenários das specs em Gherkin
uv run pytest tests/integration          # Docker real + Postgres efêmero
uv run pytest tests/e2e                  # browser (Playwright) contra o stack, do zero
```

A suíte E2E roda contra um **stack dedicado e isolado** (porta 8081, harness sempre fake, bancos e workspaces próprios) — nunca toca no portal nem nos sistemas do ambiente real:

```bash
docker compose -f deploy/docker-compose.e2e.yml up -d --build
cd portal && uv run pytest tests/e2e     # browser (Playwright), do zero, no stack 8081
```

### Cenário com LLM real (`@llm_real`)

O caminho opencode+GLM é validado manualmente (não roda em CI):

1. Suba o stack com `APPAIFORGE_HARNESS_MODE=opencode` e a chave GLM cadastrada.
2. Crie um sistema apontando para um **banco de homologação** (ADR 0015: a app usa a mesma credencial da conexão, com escrita; o gate de destrutivas protege as operações).
3. No chat: "analise o banco via MCP e crie um CRUD da tabela <x>".
4. Verifique: eventos de ferramenta no chat, app gerada em `/apps/<slug>`, MCP visível em `GET /mcp/status` do container do sistema.

## Operação

- **Rollback**: página do sistema → Checkpoints → Restaurar.
- **Arquivar** (dono): para o container, preserva o workspace, remove a rota. **Excluir** (admin, só para arquivados): remove container + workspace.
- **Logs**: `docker compose logs -f portal` / `docker logs appaiforge-sys-<slug>`.
- **Saúde das conexões**: cada conexão é sondada periodicamente e exibe seu estado na página do sistema.
- **Auditoria**: toda ação de escrita da gestão (sistemas, conexões, usuários, provedores) fica numa trilha sem segredos, global para o admin e por sistema.
- **Estado da app**: o monitor marca `erro — app fora do ar` após 3 sondas falhas e recupera sozinho quando a app volta.
- **Reconciliação**: no boot e periodicamente o portal recria containers ausentes (workspace persiste no bind).
- **Backup**: volumes do Postgres do portal + diretório de workspaces (`APPAIFORGE_WORKSPACES_DIR`).

## Estrutura

```
portal/       appaiforge/ (FastAPI+NiceGUI), tests/ (unit, bdd, integration, e2e), migrations/
base-image/   Dockerfile da imagem dos sistemas + afsupervisor (PID 1) + gated-mcp/ (MCP somente leitura com o gate)
deploy/       docker-compose.yml (postgres, mysql, traefik, portal) e docker-compose.e2e.yml
docs/adr/     decisões de arquitetura
openspec/     specs vigentes (specs/) e histórico de changes (changes/archive/)
```
