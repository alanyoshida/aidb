# AIDB

Portal que cria **sistemas de gestão com IA sobre seus bancos de dados**: você cadastra um sistema, conecta um banco (PostgreSQL, MySQL ou BigQuery), conversa com o agente pelo chat do portal e ele gera uma app administrativa (NiceGUI, 100% Python) que sobe automaticamente e fica acessível em `/apps/<slug>`.

## Destaques

- **Gera apps administrativas reais a partir de um chat em PT-BR**, sobre o schema de verdade do seu banco (via MCP) — não um template estático. Checkpoints permitem voltar o código a qualquer ponto.
- **Isolamento de verdade por sistema**: cada container roda confinado por seccomp + Landlock, aplicado pelo kernel — não depende de aprovar um pedido de permissão no chat (ver [Segurança](#segurança)).
- **Gate de SQL no data plane**: um `DROP` ou `DELETE` sem `WHERE` nunca chega ao banco — recusado por um sidecar classificador, sem pedir aprovação a ninguém.
- **Segredos nunca tocam o container do sistema**: credenciais de banco e chaves de LLM ficam cifradas no portal; com o broker de inferência (opcional), o sistema nem recebe a chave real — só um token opaco revogável.
- **Mesma lógica de negócio em Docker ou Kubernetes**: o driver de provisionamento é uma abstração comum, validada ponta a ponta nos dois (ver [Instalação](#instalação)).
- **Pilha 100% Python**, do portal (FastAPI + NiceGUI) à app gerada (NiceGUI) — sem troca de linguagem/framework em nenhuma camada.

## Arquitetura

```
Traefik (edge)
   │
   ▼
Portal FastAPI + NiceGUI  (auth/RBAC, chat, proxy)
   │  provisiona
   ▼
1 container por sistema  (supervisor + "opencode serve" + app gerada)
   │  MCP somente leitura (agente) / driver direto (app)
   ▼
Banco de produção  (PostgreSQL, MySQL ou BigQuery)
```

- Decisões de arquitetura: [`docs/adr/`](docs/adr/README.md) (21 ADRs, formato MADR).
- Especificações formais: `openspec/specs/` (13 capacidades); histórico de mudanças em `openspec/changes/archive/`.

## Dependências

- Docker 24+ com Compose v2
- Porta 80 livre
- ~2 GB RAM por sistema ativo (padrão; ver [Configuração](docs/configuracao.md) para limites)

## Instalação

Duas formas de subir o portal, conforme o **driver de provisionamento** (o que materializa cada
sistema — container Docker ou Pod Kubernetes). O driver padrão, e o único validado para produção,
é o Docker.

### Opção 1 — Docker (padrão, produção)

```bash
cd deploy
docker compose up -d --build          # postgres + mysql + traefik + portal
docker compose exec portal alembic upgrade head   # migrações (opcional: o portal cria o schema no boot)
```

- O serviço `mysql` do compose existe só como banco de teste para cadastrar conexões MySQL (host `mysql`, porta 3306, banco/usuário/senha `appaiforge`); as portas dos bancos não são publicadas no host.
- Portal: http://localhost (admin semeado em dev: `admin@appaiforge.local` / `admin123` — `APPAIFORGE_SEED_DEMO_ADMIN=1` no compose)
- Health: http://localhost/api/health

Em vez do admin semeado, crie o primeiro admin por CLI (produção):

```bash
docker compose -f deploy/docker-compose.yml exec portal appaiforge create-admin --email voce@empresa.com --password 'uma-senha-forte'
# e remova a variável APPAIFORGE_SEED_DEMO_ADMIN do compose
```

Sem chave de LLM cadastrada, o portal opera em **modo fake** (todo o resto funciona) — para geração real, ver [Chave de LLM e broker de inferência](docs/llm-e-broker.md).

### Opção 2 — Kubernetes (driver alternativo, validação local)

```bash
docker build -f deploy/portal.Dockerfile -t appaiforge/portal:0.1.0 .
kind load docker-image appaiforge/portal:0.1.0 --name appaiforge-dev

helm install appaiforge-portal deploy/helm/appaiforge-portal \
  --namespace appaiforge --create-namespace \
  --kube-context kind-appaiforge-dev
```

Materializa cada sistema como um Pod em vez de container Docker; só validado contra um cluster
`kind` local (nunca contra um cluster gerenciado real). Detalhes, pré-requisitos (Traefik no
cluster) e o chart Helm completo: [Driver Kubernetes](docs/driver-kubernetes.md).

## Segurança

Cada sistema roda isolado, com várias camadas independentes — uma falha numa não derruba as outras:

- **Confinamento do agente** (3 modos de execução; `sandboxed` por padrão quando o host suporta
  Landlock, senão cai para `reduced` com aviso): seccomp nega um denylist de syscalls perigosas e
  Landlock nega acesso a filesystem/rede fora do declarado no perfil do agente — aplicados pelo
  próprio supervisor (PID 1), irrevogáveis, sem depender de ninguém clicar "Aprovar"
  ([ADR 0018](docs/adr/0018-perfil-de-runtime-do-agente-e-identidade-reduzida.md),
  [ADR 0019](docs/adr/0019-sandbox-seccomp-landlock-no-supervisor.md)).
- **Proxy HTTP(S) de saída obrigatório por sistema**: a única saída de internet do agente passa
  por um sidecar com allow-list calculada (provedor de LLM/broker + registros de pacote) —
  `443`/`80` saíram do Landlock fixo exatamente por isso
  ([ADR 0024](docs/adr/0024-proxy-http-s-de-saida-obrigatorio-por-sistema.md)).
- **Gate de operações destrutivas**: toda SQL que toca um banco de conexão passa por um
  classificador (sqlglot) rodando num sidecar no data plane. No modo `enforce` (default),
  `DROP`/`TRUNCATE`/`ALTER` e `DELETE`/`UPDATE` sem escopo por chave são recusados na hora, sem
  pedir aprovação a ninguém; o modo `shadow` classifica e audita sem bloquear, para observar um
  sistema antes de confiar nele
  ([ADR 0017](docs/adr/0017-gate-de-operacoes-destrutivas-com-classificador-sql.md),
  [ADR 0021](docs/adr/0021-gate-de-sql-no-data-plane-via-sidecar-proxy.md)).
- **Segredos cifrados em repouso**: chaves de provedor de LLM e credenciais de conexão de banco
  ficam cifradas no Postgres do portal, nunca em texto puro
  ([ADR 0007](docs/adr/0007-metadados-em-postgres-e-credenciais-cifradas.md)).
- **RBAC**: tipo global por usuário — `admin` (tudo), `editor` (cria e gerencia sistemas) ou
  `app_user` (só usa as apps de sistemas a que tem acesso); sem papel por sistema
  ([ADR 0014](docs/adr/0014-rbac-com-tipos-globais-de-usuario.md)).
- **Broker de inferência** (opcional): o container do sistema carrega só um token opaco em vez da
  chave do provedor, revogável por sistema ou por sessão de chat
  ([ADR 0020](docs/adr/0020-broker-de-inferencia-com-litellm.md), ver [LLM e broker](docs/llm-e-broker.md)).
- **Auditoria**: toda ação de escrita da gestão e toda decisão do gate (aprovada/recusada/
  bloqueada) fica numa trilha sem segredos.

Confinamento do agente e gate de destrutivas por dentro: [`docs/seguranca.md`](docs/seguranca.md).
Broker de inferência: [`docs/llm-e-broker.md`](docs/llm-e-broker.md). Segredos cifrados e RBAC:
os ADRs linkados acima.

## Documentação

| Tema | Onde |
|---|---|
| Criar um sistema, chat, editor, aparência | [`docs/guia-de-uso.md`](docs/guia-de-uso.md) |
| Gate de operações destrutivas e confinamento do agente | [`docs/seguranca.md`](docs/seguranca.md) |
| Chave de LLM e broker de inferência (LiteLLM) | [`docs/llm-e-broker.md`](docs/llm-e-broker.md) |
| Instalação sob o driver Kubernetes (chart Helm) | [`docs/driver-kubernetes.md`](docs/driver-kubernetes.md) |
| Todas as variáveis de ambiente `APPAIFORGE_*` | [`docs/configuracao.md`](docs/configuracao.md) |
| Rodar a suíte de testes (unit/BDD/integration/E2E) | [`docs/testes.md`](docs/testes.md) |
| Rollback, logs, auditoria, backup, reconciliação | [`docs/operacao.md`](docs/operacao.md) |
| Decisões de arquitetura (ADRs) | [`docs/adr/`](docs/adr/README.md) |
| Roadmap de confinamento do agente | [`docs/roadmap-confinamento-do-agente.md`](docs/roadmap-confinamento-do-agente.md) |

## Estrutura

```
portal/       appaiforge/ (FastAPI+NiceGUI), tests/ (unit, bdd, integration, e2e), migrations/
base-image/   Dockerfile da imagem dos sistemas + afsupervisor (PID 1) + gated-mcp/ (MCP somente leitura com o gate)
deploy/       docker-compose.yml (postgres, mysql, traefik, portal), docker-compose.e2e.yml e helm/ (chart do portal p/ driver Kubernetes)
docs/         guias de uso, segurança, configuração etc. (acima) e docs/adr/ (decisões de arquitetura)
openspec/     specs vigentes (specs/) e histórico de changes (changes/archive/)
```
