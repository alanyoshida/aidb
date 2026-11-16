# AIDB

Portal que cria **sistemas de gestão com IA sobre seus bancos de dados**: você cadastra um sistema, conecta um banco (PostgreSQL, MySQL ou BigQuery), conversa com o agente pelo chat do portal e ele gera uma app administrativa (NiceGUI, 100% Python) que sobe automaticamente e fica acessível em `/apps/<slug>`.

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

- Cada sistema roda isolado no seu próprio container, confinado por padrão (seccomp + Landlock) — ver [Segurança](docs/seguranca.md).
- Toda SQL que toca um banco de conexão passa por um gate classificador antes de chegar lá — ver [Segurança](docs/seguranca.md).
- Decisões de arquitetura: [`docs/adr/`](docs/adr/README.md) (21 ADRs, formato MADR).
- Especificações formais: `openspec/specs/` (13 capacidades); histórico de mudanças em `openspec/changes/archive/`.

## Dependências

- Docker 24+ com Compose v2
- Porta 80 livre
- ~2 GB RAM por sistema ativo (padrão; ver [Configuração](docs/configuracao.md) para limites)

## Instalação

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

Instalação alternativa, sob o driver de provisionamento Kubernetes (validação local via `kind` + Helm): ver [Driver Kubernetes](docs/driver-kubernetes.md).

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
