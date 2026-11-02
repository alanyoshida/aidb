# AGENTS.md

Guia para agentes que trabalham neste repositório. Produto: **AppAIForge** — portal que gera
apps de gestão (NiceGUI, Python) sobre bancos PostgreSQL, conduzido por chat. A documentação de
produto fica no [`README.md`](README.md); decisões em [`docs/adr/`](docs/adr/README.md).

## Estrutura

- `portal/` — app FastAPI + NiceGUI (`appaiforge/`), migrações (`migrations/`), testes (`tests/`).
- `base-image/` — Dockerfile da imagem dos sistemas + `afsupervisor` (PID 1) + `gated-mcp/`.
- `deploy/` — `docker-compose.yml` (postgres, traefik, portal) e `docker-compose.e2e.yml`.
- `docs/adr/` — decisões de arquitetura (MADR). `openspec/` — specs e change ativa.

## Comandos

```bash
# Stack local (do zero)
cd deploy && docker compose up -d --build
docker compose exec portal alembic upgrade head

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
  `confirmável` aguarda aprovação, **DDL é sempre bloqueada** (ADR 0017). Não burle essa camada.
- Credenciais são cifradas nos metadados (ADR 0007); nunca logue segredos nem os inclua em commits.

## Fluxo OpenSpec

Mudanças seguem o workflow OpenSpec (specs em `openspec/specs/`, propostas em
`openspec/changes/`). Antes de implementar, leia a change ativa e a spec afetada. Não edite specs
diretamente para refletir código novo sem passar pelo fluxo de change.