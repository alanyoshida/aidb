# AIDB

[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![NiceGUI](https://img.shields.io/badge/NiceGUI-3.18-5898D4)](https://nicegui.io/)
[![Bancos: PostgreSQL | MySQL | BigQuery](https://img.shields.io/badge/bancos-PostgreSQL%20%7C%20MySQL%20%7C%20BigQuery-4169E1?logo=postgresql&logoColor=white)](docs/guia-de-uso.md)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](#instalação)
[![Kubernetes (Helm)](https://img.shields.io/badge/Kubernetes-Helm-326CE5?logo=kubernetes&logoColor=white)](docs/driver-kubernetes.md)
[![Agente: opencode](https://img.shields.io/badge/agente-opencode%201.19-black)](https://opencode.ai/)
[![Specs: OpenSpec](https://img.shields.io/badge/specs-OpenSpec-6E40C9)](openspec/specs/)
[![Último commit](https://img.shields.io/github/last-commit/alanyoshida/aidb)](https://github.com/alanyoshida/aidb/commits/main)

Portal que cria **sistemas de gestão com IA sobre seus bancos de dados**: você cadastra um sistema, conecta um banco (PostgreSQL, MySQL ou BigQuery), conversa com o agente pelo chat do portal e ele gera uma app administrativa (NiceGUI, 100% Python) que sobe automaticamente e fica acessível em `/apps/<slug>`.

## Destaques

- **Gera apps administrativas reais a partir de um chat em PT-BR**, sobre o schema de verdade do seu banco (via MCP) — não um template estático. Checkpoints permitem voltar o código a qualquer ponto.
- **Isolamento de verdade por sistema**: cada container roda confinado por seccomp + Landlock, aplicado pelo kernel — não depende de aprovar um pedido de permissão no chat (ver [Segurança](#segurança)).
- **Gate de SQL no data plane**: um `DROP` ou `DELETE` sem `WHERE` nunca chega ao banco — recusado por um sidecar classificador, sem pedir aprovação a ninguém.
- **Segredos nunca tocam o container do sistema**: credenciais de banco e chaves de LLM ficam cifradas no portal; com o broker de inferência (opcional), o sistema nem recebe a chave real — só um token opaco revogável.
- **Mesma lógica de negócio em Docker ou Kubernetes**: o driver de provisionamento é uma abstração comum, validada ponta a ponta nos dois (ver [Instalação](#instalação)).
- **Mudanças planejadas pelo chat com OpenSpec**: o agente de cada sistema já vem com o OpenSpec
  1.15.0 (versão pinada na imagem base, sem depender de rede) e os comandos `/opsx-propose`,
  `/opsx-explore`, `/opsx-apply` e `/opsx-archive`. Ao digitar `/` no chat, o campo sugere os
  comandos disponíveis no agente daquele sistema (ver [guia de uso](docs/guia-de-uso.md#chat)).
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
docker build -f deploy/portal.Dockerfile -t appaiforge/portal:1.12.0 .
kind load docker-image appaiforge/portal:1.12.0 --name appaiforge-dev

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
- **Autenticação local ou SSO (OIDC)**, escolhida por ENV e travada na instalação, com admin
  break-glass; o acesso a cada app é verificado pelo portal a cada requisição e a app recebe a
  identidade num JWT restrito a ela ([ADR 0027](docs/adr/0027-sso-oidc-e-identidade-das-apps-por-forwardauth.md),
  ver [Autenticação](docs/autenticacao.md)).
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
| Login local, SSO por OIDC (Keycloak), break-glass e acesso às apps | [`docs/autenticacao.md`](docs/autenticacao.md) |
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

## Licença

Distribuído sob a licença MIT: uso, modificação e redistribuição livres, inclusive para fins comerciais, desde que o aviso de copyright e o texto da licença acompanhem as cópias. Veja [`LICENSE`](LICENSE).
