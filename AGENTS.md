# AGENTS.md

Guia para agentes que trabalham neste repositório. Produto: **AIDB** — portal que gera
apps de gestão (NiceGUI, Python) sobre bancos PostgreSQL, MySQL e BigQuery, conduzido por chat. A documentação de
produto fica no [`README.md`](README.md); decisões em [`docs/adr/`](docs/adr/README.md).

## Estrutura

- `portal/` — app FastAPI + NiceGUI (`appaiforge/`), migrações (`migrations/`), testes (`tests/`).
  - `appaiforge/ui/` — páginas NiceGUI; `ui/theme.py` define tema e tokens, `ui/common.py` o `notify()` e a topbar, `ui/chat.py` o chat.
  - `appaiforge/harness/` — adapters do agente (`opencode.py` real, `fake.py` determinístico).
  - `appaiforge/services/` — conexões, provedores/chaves de LLM, auditoria, catálogo.
- `base-image/` — Dockerfile da imagem dos sistemas + `afsupervisor` (PID 1) + `gated-mcp/`.
- `deploy/` — `docker-compose.yml` (postgres, mysql, traefik, portal) e `docker-compose.e2e.yml`.
- `docs/adr/` — decisões de arquitetura (MADR). `openspec/specs/` — specs vigentes;
  `openspec/changes/` — changes ativas; `openspec/changes/archive/` — histórico.
- `docs/roadmap-confinamento-do-agente.md` — roadmap de longa duração (9 etapas, uma change por
  etapa) de confinamento e política do agente. Leia antes de propor change nessa área.

## Comandos

```bash
# Stack local (do zero)
cd deploy && docker compose up -d --build
docker compose exec portal alembic upgrade head
# O código do portal vai dentro da imagem (sem bind do host): após editar, rebuild
docker compose -f deploy/docker-compose.yml build portal && docker compose -f deploy/docker-compose.yml up -d portal

# Testes (a partir de portal/)
uv sync
uv run pytest tests/unit          # rápidos, sem Docker
uv run pytest tests/bdd           # cenários Gherkin das specs
uv run pytest tests/integration   # Docker real + Postgres efêmero
uv run pytest tests/e2e           # Playwright contra o stack E2E

# E2E isolado (porta 8081, harness fake, nunca toca o ambiente real)
docker compose -f deploy/docker-compose.e2e.yml up -d --build
cd portal && uv run pytest tests/e2e
```

Não há config de lint/format (ruff/black) no repositório — não invente uma; siga o estilo existente.

## Convenções

- Idioma do produto e do código: **PT-BR** (UI, comentários de domínio, mensagens). Sem comentários
  novos no código, a menos que pedido.
- Marque testes novos com os markers já definidos: `e2e`, `integration`, `llm_real`
  (`llm_real` nunca roda em CI).
- A suíte E2E nunca deve apontar para o stack de produção; use o compose E2E dedicado (8081).
- Toda SQL contra bancos de conexão passa pelo **gate** (`gate.py`): `normal` executa,
  `confirmável` aguarda aprovação, **DDL é sempre bloqueada** (ADR 0017, spec `destructive-gate`). Não burle essa camada.
- Credenciais são cifradas nos metadados (ADR 0007); nunca logue segredos nem os inclua em commits.
  A config do agente (chaves, MCP) vive em `CONFIGS_DIR`, fora do workspace que o agente edita.
- Cores da UI: use os tokens `--ap-*` / `--ch-*` e `ui/common.py:notify()`; não fixe cores nem use
  `ui.notify(type=...)` (o Quasar sobrescreve o tema). Todo par texto/fundo novo deve manter contraste
  WCAG AA nas 12 combinações de tema (spec `portal-theming`).
- Horários são gravados em UTC e convertidos na UI por `display_timezone`.
- Mudança de schema exige migração Alembic encadeada ao head atual (`alembic heads` deve listar um só).
- O compose sobe em harness `fake` por padrão; para o agente real use `APPAIFORGE_HARNESS_MODE=opencode`
  (em `deploy/.env`, não versionado).

## Fluxo OpenSpec

Mudanças seguem o workflow OpenSpec (specs em `openspec/specs/`, propostas em
`openspec/changes/`). Antes de implementar, leia a change ativa (se houver) e a spec afetada. Não edite
specs diretamente para refletir código novo sem passar pelo fluxo de change: propor → aplicar →
arquivar (o arquivamento sincroniza os deltas para `openspec/specs/`). Mudança de decisão arquitetural
vira ADR sequencial em `docs/adr/` (o próximo número é 0018).